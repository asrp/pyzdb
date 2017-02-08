import zmq
from zmq.devices import ProcessDevice
import random
from undoable import observed_dict, UndoLog, deepwrap
from util import File, Encoder
import json
import traceback
import sys, os, errno
from cStringIO import StringIO
import time
#from lock import acquire_lock, release_lock
import cPickle as pickle
import copy_reg
import types
import shutil
import logging

def reduce_method(m):
    return (getattr, (m.__self__, m.__func__.__name__))

copy_reg.pickle(types.MethodType, reduce_method)

class Database(observed_dict):
    @staticmethod
    def load(filename, *args, **kwargs):
        if os.path.isfile(filename):
            # Hack! Need to debug.
            output = pickle.load(open(filename))
            output.undolog.undoroot = output.undolog.root
            output.timestamp = os.stat(filename).st_mtime
            return output
        else:
            return Database(filename, *args, **kwargs)

    def __init__(self, filename, bigfiledir=os.path.join([".", "bigfiles"]),
                 *args, **kwargs):
        observed_dict.__init__(self, *args, **kwargs)
        self.undolog = UndoLog()
        self.undolog.add(self)
        self.filename = filename
        self.bigfiledir = bigfiledir
        self.timestamp = 0

    def save(self):
        #acquire_lock(self.filename + ".lock", "exclusive")
        pickle.dump(self, open(self.filename + ".new", "w"))
        os.rename(self.filename + ".new", self.filename)
        #release_lock(self.filename + ".lock")

    def newfile(self, filename):
        self["_filenum"] = self.get("_filenum", 0) + 1
        location = os.path.join(self.bigfiledir, str(self["_filenum"]))
        self["_files"][location] = filename
        return os.path.join(self.bigfiledir, str(self["_filenum"]))

    def wrapfile(self, elem):
        if type(elem) == dict and "_customtype" in elem:
            if elem["_customtype"] == "file":
                newname = self.newfile(elem["filename"])
                if "content" not in elem:
                    shutil.move(os.path.join(elem["location"]), newname)
                    return File(newname, elem["filename"])
                else:
                    open(newname, "w").write(elem["content"])
                    return File(newname, newname)
        else:
            return None

    def undo(self):
        self.undolog.undo()

    def redo(self):
        self.undolog.redo()

def router_dealer(client_uri, server_uri, prefix='write'):
    pd = ProcessDevice(zmq.QUEUE, zmq.ROUTER, zmq.DEALER)
    pd.bind_in(client_uri)
    pd.bind_out(server_uri)
    pd.setsockopt_in(zmq.IDENTITY, '%s-router' % prefix)
    pd.setsockopt_out(zmq.IDENTITY, '%s-dealer' % prefix)
    return pd

class Server(object):
    def __init__(self, db, server_uri, lock_uri=None, read_only=False):
        self.server_uri = server_uri
        self.rep_uri = server_uri.replace("*", "localhost")
        self.lock_uri = lock_uri
        self.auto_reload = zmq.NOBLOCK if read_only else 0
        self.read_only = read_only
        self.db = db
        self.running = False

    def start(self):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REP)
        self.socket.connect(self.rep_uri)

    def reload_db(self, filename=None):
        filename = filename if filename is not None else self.db.filename
        if not os.path.isfile(filename) or self.db.timestamp < os.stat(filename).st_mtime:
            if os.path.isfile(filename):
                logging.debug("Reloading database from %s", filename)
                logging.debug("Timestamps old=%s new=%s", self.db.timestamp, os.stat(filename).st_mtime)
            self.db = Database.load(filename)

    def run(self):
        self.running = True
        while self.running:
            try:
                message = self.socket.recv(self.auto_reload)
            except zmq.ZMQError as e:
                self.reload_db()
                time.sleep(0.1)
                continue
            logging.debug("Received request: %s" % message)
            try:
                message = json.loads(message)
                if message["mode"] == "exec":
                    # Make extra checks here
                    old_stdout = sys.stdout
                    stdout = sys.stdout = StringIO()
                    try:
                        co = compile(message["command"], "<remote>", "single")
                        exec co in globals()
                    except:
                        output = sys.exc_info()
                    else:
                        output = stdout.getvalue()
                    sys.stdout = old_stdout
                elif message["mode"] == "readall":
                    output = db
                elif message["mode"] == "lock":
                    assert(not self.read_only)
                    output = {"locked": True, "uri": self.lock_uri}
                elif message["mode"] == "unlock":
                    assert(not self.read_only)
                    output = {"locked": False}
                else:
                    entry = self.db
                    for key in message["index"]:
                        entry = entry[key]
                    if not message.get("func"):
                        output = entry
                    else:
                        func = getattr(entry, message["func"])
                        message["args"] = deepwrap(message["args"], entry.callbacks, entry.undocallbacks, self.db.wrapfile, skiproot=True)
                        message["kwargs"] = deepwrap(message["kwargs"], entry.callbacks, entry.undocallbacks, self.db.wrapfile, skiproot=True)
                        output = func(*message["args"], **message["kwargs"])
            except:
                output = traceback.format_exc()
                logging.error(traceback.print_exc())
            if type(output).__name__ in ['listiterator', 'dictionary-keyiterator']:
                output = list(output)
            try:
                output = json.dumps(output, cls=Encoder)
            except:
                output = str(output)
            self.socket.send(output)
            if message["mode"] == "lock":
                self.normal_socket = self.socket
                self.socket = zmq.Context().socket(zmq.REP)
                self.socket.bind(self.lock_uri.replace("localhost", "*"))
                logging.debug("Locked and listening on %s" % self.lock_uri)
            elif message["mode"] == "unlock":
                self.socket.close()
                self.socket = self.normal_socket
                logging.debug("Unlocked")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("db_filename", default="/tmp/db.pkl", nargs='?')
    parser.add_argument("write_client_uri", default="tcp://*:5559", nargs='?')
    parser.add_argument("write_server_uri", default="tcp://*:5560", nargs='?')
    parser.add_argument("read_client_uri", default="tcp://*:5561", nargs='?')
    parser.add_argument("read_server_uri", default="tcp://*:5562", nargs='?')
    parser.add_argument("lock_uri", default="tcp://localhost:5558", nargs='?')
    parser.add_argument("-ro", "--read-only", action="store_true")
    parser.add_argument("-v", "--verbosity", action="count", default=0)
    args = parser.parse_args()
    if args.verbosity == 1:
        logging.basicConfig(level=logging.INFO)
    elif args.verbosity >= 2:
        logging.basicConfig(level=logging.DEBUG)

    db = Database.load(args.db_filename)
    logging.info("Starting server: %s", args)
    if args.read_only:
        server = Server(db, args.read_server_uri, read_only=True)
    else:
        write_router = router_dealer(args.write_client_uri, args.write_server_uri)
        read_router = router_dealer(args.read_client_uri, args.read_server_uri)
        server = Server(db, args.write_server_uri, args.lock_uri)
        write_router.start()
        read_router.start()
    server.start()
    server.run()
