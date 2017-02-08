import zmq
import json
import traceback
from util import File, Encoder, read_only
import logging

class Caller(object):
    def __init__(self, prefix, sockets):
        self.prefix = prefix
        self._sockets = sockets

    def __getattr__(self, attrib):
        def dummyfunc(*args, **kwargs):
            self._run(attrib, args, kwargs)
        return dummyfunc

    def __iter__(self, *args, **kwargs):
        return iter(self._run("__iter__", args, kwargs))

    def __getitem__(self, *args, **kwargs):
        return Caller(self.prefix + [args[0]], self._sockets)

    def __setitem__(self, *args, **kwargs):
        self._run("__setitem__", args, kwargs)

    def __delitem__(self, *args, **kwargs):
        self._run("__delitem__", args, kwargs)

    def __len__(self, *args, **kwargs):
        return int(self._run("__len__", args, kwargs))

    def __contains__(self, *args, **kwargs):
        return self._run("__contains__", args, kwargs) == "True"

    def _run(self, func=None, args=(), kwargs=None):
        kwargs = kwargs if kwargs is not None else {}
        logging.debug("Running %s %s %s on %s", func,
                      args, kwargs, self.prefix)
        message = json.dumps({"mode": "read" if func in read_only else "write",
                              "index": self.prefix,
                              "func": func,
                              "args": args,
                              "kwargs": kwargs},
                             cls=Encoder)
        if self._sockets['lock'] is not None:
            socket = self._sockets['lock']
        elif func in read_only and self._sockets['read'] is not None:
            socket = self._sockets['read']
        else:
            socket = self._sockets['write']
        socket.send(message)
        answer = socket.recv()
        answer = json.loads(answer)
        return answer

    def lock(self):
        assert(self._sockets['lock'] is None)
        self._sockets['write'].send(json.dumps({"mode": "lock", "action": "lock"}))
        answer = json.loads(self._sockets['write'].recv())
        assert(answer["locked"] == True)
        self._uri = answer["uri"]
        logging.debug("Reconnecting on %s" % self._uri)
        self._sockets['lock'] = zmq.Context().socket(zmq.REQ)
        self._sockets['lock'].connect(answer["uri"])

    def unlock(self):
        socket = self._sockets['lock']
        socket.send(json.dumps({"mode": "unlock", "action": "unlock"}))
        answer = json.loads(socket.recv())
        assert(answer["locked"] == False)
        socket.close()
        self._sockets['lock'] = None
        del self._uri

def client(write_uri="tcp://localhost:5559", read_uri=None):
    context = zmq.Context()
    logging.debug("Connecting to server on %s %s", write_uri, read_uri)
    sockets = {"write": context.socket(zmq.REQ),
               "read": context.socket(zmq.REQ) if read_uri is not None else None,
               "lock": None}
    sockets["write"].connect(write_uri)
    if sockets["read"] is not None:
        sockets["read"].connect(read_uri)
    return Caller([], sockets), sockets

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("write_uri", default="tcp://localhost:5559", nargs='?')
    parser.add_argument("read_uri", default=None, nargs='?') #5561
    parser.add_argument("-v", "--verbosity", action="count", default=0)
    args = parser.parse_args()
    if args.verbosity >= 1:
        logging.basicConfig(level=logging.DEBUG)

    db, sockets = client(write_uri=args.write_uri, read_uri=args.read_uri,)
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
