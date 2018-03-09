"""
inspiration from https://github.com/lianemeth/forest/blob/master/forest/NaryTree.py
"""
import locale
import weakref

class Node(object):
    def __init__(self, id=None, name=None, children=None, accounts=None,
                 node_spend=0, parent=None):
        self.id = id
        self.node_spend = float(node_spend) or float(0)
        self.accounts = accounts or []
        self.children = children or []
        self._parent = weakref.ref(parent) if parent else None
        if self._parent is None:
            self.name = "ROOT"
        else:
            self.name = name

    @property
    def parent(self):
        if self._parent:
            return self._parent()

    def __iter__(self):
        yield self
        for child in self.children:
            yield child

    def add_child(self, id=None, name=None):
        child = Node(id=id, name=name, parent=self)
        self.children.append(child)
        return child

    def add_account(self, account=None):
        self.accounts.append(account)
        self.node_spend = self.node_spend + account[2]
        parent = self.parent
        while parent is not None:
            parent.node_spend = parent.node_spend + account[2]
            parent = parent.parent

        return account

    def get_accounts(self):
        return self.accounts

    def get_children(self):
        return self.children

    def get_parent_path(self):
        if self.parent is None:
            return

        parent = self.parent
        parent_path = [parent.name]
        while parent.parent is not None:
            parent = parent.parent
            parent_path.append(parent.name)

        parent_path.reverse()
        return parent_path

    def print_tree(self, limit=0.0, display_ids=None, parent=None):
        limit = float(limit) or 0.0
        if self.accounts:
            locale.setlocale(locale.LC_ALL, '')
            node_spend = locale.format('%.2f', self.node_spend, grouping=True)
            node_spend = '$' + node_spend
            if self.parent is not None:
                parent_path = self.get_parent_path()
                parent_path = ' -> '.join(parent_path)
                name = self.name + ':'
                print(parent_path, '->', self.name, node_spend)
            else:
                print(self.name, node_spend)

            for account in self.get_accounts():
                if account[2] >= limit:
                    account_spend = locale.format('%.2f', account[2], grouping=True)
                    account_spend = '$' + str(account_spend)
                    if display_ids:
                        id = '(' + account[0] + ')'
                        print(account[1], id, '\t\t\t', account_spend)
                    else:
                        print(account[1], '\t\t\t\t', account_spend)

            print()

        for child in self.children:
            child.print_tree(limit, display_ids)
