import zmq
import json
import sys

context = zmq.Context()
print "Connecting to server..."
socket = context.socket(zmq.REQ)
socket.connect(sys.argv[1] if len(sys.argv)>1 else "tcp://localhost:5559")
while True:
    request = raw_input(">>> ")
    socket.send(json.dumps({"mode": "exec", "command": request}))
    message = socket.recv()
    print "Received reply", message
