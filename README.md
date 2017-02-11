# pyzdb - a lightweight database with Python syntax queries, using ZeroMQ

**Please note this project's name change from pydb to pyzdb.**

pyzdb ("pies db") is a database for storing nested `list` and `dict` and allows Python syntax queries instead of some variation of SQL. A deliberate choice is made to make no optimization on the queries so you know exactly what paths queries take.

## Installation

pyzdb depends on

- [pyzmq](https://github.com/zeromq/pyzmq)
- [undoable](https://github.com/asrp/undoable)
- [portalocker](https://pypi.python.org/pypi/portalocker) (not needed yet, under consideration)

Install with

    pip install -r requirements.txt

Note that undoable is not yet on PyPI and is installed using the `-e` flag. Alternatively, it can be downloaded manually and put in the same directory as `server.py` and `client.py`.

## Running

In one terminal, run

	python server.py

In a different terminal, run

	python client.py

to get a prompt to access the database

	> db

### Sample session

    > db
    {}
    > db['x'] = 3
    None
    > db['x']
    3
    > db['l'] = range(10)
    None
    > db
    {u'x': 3, u'l': [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]}
    > db['l'][4] = ['a', 'b', 'c']
    None
    > db.undo()
    None
    > db
    {u'x': 3, u'l': [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]}
    > db.undo()
    None
    > db.redo()
    None
    > db.redo()
    None
    > db
    {u'x': 3, u'l': [0, 1, 2, 3, [u'a', u'b', u'c'], 5, 6, 7, 8, 9]}
    > [v for v in db['l'][4]]
    [u'a', u'b', u'c']
	> [k for k in db]
	[u'x', u'l']
    > db['l'][4].append('d')
    > db.save()

The server can be stopped and restarted to continue the session (without needing to restart the client). The most common use in an application is to import and use the client while the server is still run the same way.

    from pyzdb.client import client
    db, socket = client()
    db['x'] = 3
    x = db['x']._run()
    db['l'] = range(10)
    odd_squares = [v*v for v in db['l'] if v%2]
    db.save()

### `lock` example

    from pyzdb.client import client
    db, socket = client()
    db.lock()
    x = db['x']._run()
    db['x'] = x + 1
    db.unlock()

(or simply `db['x'] = db['x']._run() + 1` but this will also run *two* queries instead of one.)

### Multiple read-only servers example

In one terminal

	python server.py

In a second terminal

	python server.py -ro

In a third terminal

    python client.py tcp://localhost:5559 tcp://localhost:5561

And proceed as previous examples.

`tcp://localhost:5559` is the read-write URI and `tcp://localhost:5561` is the read-only URI.

Note that all reads gets data from some consistent version of the database that's not necessarily the latest version so something like this from the client is possible.

    > db['x'] = 3
    None
    > db.save()
    None
    > db['x'] = 4
    None
    > db.save()
    None
    > db['x']
    3

If no parameters are passed to `client.py` or only a single parameter (the read-write URI), the client will only connect to the read-write server. This is the intended method for using only one database server.

## Intended use

One intended use is a single instance of the database server with any number of clients (for example a web server) running on the same machine. The total database size isn't too large and large chunks are stored externally in files and represented by `File` objects in the database.

Another possibility is to have a single read-write server with multiple read-only server. The read-only server reload the database from the filesystem so to update them, update the database file.

## Architecture

![Architecture](https://asrp.github.io/blog/multi-write-architecture.svg)

`server.py` (with no arguments) starts

- one queued router-dealer for read-only servers
- one queued router-dealer for a read-write server
- a read-write reply (`zmq.REP`) server.

The router-dealers serializes (and queues) incoming requests and sends one request at a time to the reply server of the right type. The reply server handles the request and answers the client (of that request).

All messages are encoded in JSON.

[This post discusses choices when multiple read-only servers were added](https://asrp.github.io/blog/pyzdb_multiple_read.html).

## Debugging

`exec_client.py` is provided to help debugging. All requests sent from the client are executed (`exec in globals()`) on the server. This feature should probably be disabled for any public-facing program (safest would be to delete it from `server.py`).

## Features and non-features

### Data type

All data is JSON encoded and decoded so only JSON-encodable data can be stored, although its possible to write your own encoder to support more types of data.

### Connection type

In theory, this database could allow any type of connection that ZeroMQ allows but most tests were done using TCP.

### Query syntax

As seen the above examples, the first argument returned by `client` is treated as the root of nested `list` and `dict` and regular Python syntax is used to describe the entries we want to read or modify from that root (such as `db['l'][4]`).

To read an entry that is not an iterator, an extra `._run()` function needs to be called (such as `db['l'][4]._run()`). This is because of the lazy evaluation implemented so `db['l'][4]` never actually sends any requests.

### Serializability

`lock` and `unlock` in allows a client to get exclusive access to the database. No writes *or reads* are possible from other clients in the meantime. The client program has to be written so the order in which other accesses are treated are unimportant.

No deadlock (dead client) checks are implemented.

No support for locking only part of the database is implemented although this could be implemented using `lock` and `unlock`.

    db.lock()
    if not db['locks'].get(('l', 4), False) and not db['locks'].get(('l'), False):
        db['locks'][('l', 4)] = True
    else:
        db.unlock()
        # return and do something else meanwhile
    db.unlock()
    # Do stuff on db['l'][4]
    db.lock()
    assert(db['locks'].get(('l', 4), False))
    db['locks'][('l', 4)] = False
    db.unlock()

### Disk storage

The database itself is stored as a single pickled file but large blobs can be stored on the filesystem and a path in the database. If the client is on the same

Large files are "transfered" using a `File("/path/to/file")` object. The file needs to already be on the server's filesystem before a `File` object is stored.

### Rollback

`Server.undo` and `Server.redo` are available but need to be called manually from a client.

### Multiple database servers

Its now possible to have multiple read-only servers and one read-write server.

The read-only servers should reload the database from disk periodically (with the database file made available to them through some other means like a network filesystem or simply copying). No system for sending just the changes are available out of the box.

### Authentication

There is no authentication mechanism. The intended usage is to have appropriate firewall rules outside the database.

## Discussion

[Here is a discussion about adding multiple read-only servers](https://asrp.github.io/blog/pyzdb_multiple_read.html)

## Other similar projects

- [Tinydb](https://github.com/msiemens/tinydb)
- [Python's shelve](https://docs.python.org/2/library/shelve.html)
- [Blitzdb](https://github.com/adewes/blitzdb)
