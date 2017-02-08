import json

class Encoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, File):
            return {"_customtype":"file", "filename": obj.filename, "location": obj.location}
        else:
            return json.JSONEncoder.default(self, obj)

class File(object):
    def __init__(self, location, filename = None):
        self.location = location
        if filename is None:
            filename = os.path.basename(location)
        self.filename = filename

read_only = [None, "__getitem__", "__iter__", "__len__", "__contains__", "keys", "items", "values", "get", "__eq__", "__ne__"]
