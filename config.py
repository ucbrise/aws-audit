import collections

# set up named tuples
NodeInfo = collections.namedtuple('NodeInfo', ['id', 'name'])
Account = collections.namedtuple('Account', ['id', 'name'])
AccountInfo = collections.namedtuple('AccountInfo',
                                     ['id', 'name', 'total', 'currency'])
