import zmq
import json
import traceback
from util import File, Encoder
import logging

class Caller(object):
    def __init__(self, prefix, socket):
        self.prefix = prefix
        self._socket = socket

    def __getattr__(self, attrib):
        def dummyfunc(*args, **kwargs):
            self._run(attrib, args, kwargs)
        return dummyfunc

    def __iter__(self, *args, **kwargs):
        return iter(self._run("__iter__", args, kwargs))

    def __getitem__(self, *args, **kwargs):
        return Caller(self.prefix + [args[0]], self._socket)
        #self._run("__getitem__", args, kwargs)

    def __setitem__(self, *args, **kwargs):
        self._run("__setitem__", args, kwargs)

    def __delitem__(self, *args, **kwargs):
        self._run("__delitem__", args, kwargs)

    def __len__(self, *args, **kwargs):
        return int(self._run("__len__", args, kwargs))

    def __contains__(self, *args, **kwargs):
        return self._run("__contains__", args, kwargs) == "True"

    def _run(self, func=None, args=(), kwargs={}):
        logging.debug("Running %s %s %s on %s", func,
                      args, kwargs, self.prefix)
        message = json.dumps({"mode": "run",
                              "index": self.prefix,
                              "func": func,
                              "args": args,
                              "kwargs": kwargs},
                             cls=Encoder)
        self._socket.send(message)
        answer = self._socket.recv()
        answer = json.loads(answer)
        return answer

    def lock(self):
        self._socket.send(json.dumps({"mode": "lock", "action": "lock"}))
        answer = json.loads(self._socket.recv())
        assert(answer["locked"] == True)
        logging.debug("Reconnecting on %s" % answer["uri"])
        self._normal_socket = self._socket
        self._socket = zmq.Context().socket(zmq.REQ)
        self._socket.connect(answer["uri"])
        self._uri = answer["uri"]

    def unlock(self):
        self._socket.send(json.dumps({"mode": "unlock", "action": "unlock"}))
        answer = json.loads(self._socket.recv())
        assert(answer["locked"] == False)
        self._socket.close()
        del self._uri
        self._socket = self._normal_socket

def client(uri="tcp://localhost:5559"):
    context = zmq.Context()
    logging.debug("Connecting to server on %s" % uri)
    socket = context.socket(zmq.REQ)
    socket.connect(uri)
    return Caller([], socket), socket

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("in_uri", default="tcp://*:5559", nargs='?')
    parser.add_argument("-v", "--verbosity", action="count", default=0)
    args = parser.parse_args()
    if args.verbosity >= 1:
        logging.basicConfig(level=logging.DEBUG)

    db, socket = client()
    while True:
        command = raw_input("> ")
        try:
            try:
                co = compile(command, "<command-line>", "eval")
            except SyntaxError:
                co = compile(command, "<command-line>", "exec")

            ret = eval(co, globals())
            # getitem heuristic guess
            if type(ret) == Caller:
                ret = ret._run()
            print ret
        except:
            traceback.print_exc()
