from collections import namedtuple

# set up named tuples
NodeInfo = namedtuple('NodeInfo', ['id', 'name'])
Account = namedtuple('Account', ['id', 'name'])
AccountInfo = namedtuple('AccountInfo',
                         ['id', 'name', 'total', 'currency'])
