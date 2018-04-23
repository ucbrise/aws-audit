"""
inspiration from https://github.com/lianemeth/forest/blob/master/forest/NaryTree.py
"""
import locale
import os
import sys
import weakref

class Node(object):
  """
  an n-ary tree implementation to store AWS OU and account information
  """
  def __init__(self, id=None, name=None, children=None, accounts=None,
               node_spend=0, node_account_spend=0, parent=None, currency=None):
      self.id = id
      self.node_spend = float(node_spend) or float(0)
      self.node_account_spend = float(node_account_spend) or float(0)
      self.accounts = accounts or []
      self.children = children or []
      self.currency = currency or None
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

  def add_child(self, id=None, name=None, currency=None):
    """
    adds an OU child to the parent node

    args:
      id:    AWS ID for the new child
      name:  human readable name of the child
      currency:  default currency for this node

    returns:
      child: new child object
    """
    child = Node(id=id, name=name, currency=currency, parent=self)
    self.children.append(child)
    return child

  def add_account(self, account=None):
    """
    adds an AWS account to the leaf of the tree and adds the account spend
    to the node spend (as well as adding up to the root node)

    args:
      account: tuple of (account id, real name, account spend, currency)

    returns:
      account: tuple of (account id, real name, account spend, currency)
    """
    self.accounts.append(account)
    self.node_spend = self.node_spend + account.total
    self.node_account_spend = self.node_account_spend + account.total
    parent = self.parent
    while parent is not None:
      parent.node_spend = parent.node_spend + account.total
      parent = parent.parent

    return account

  def get_accounts(self):
    return self.accounts

  def get_children(self):
    return self.children

  def get_parent_path(self):
    """
    get the path from root to the current node

    args:
      none

    returns:
      parent_path:  list containing path from root to the current node
    """
    if self.parent is None:
      return

    parent = self.parent
    parent_path = [parent.name]
    while parent.parent is not None:
      parent = parent.parent
      parent_path.append(parent.name)

    parent_path.reverse()
    return parent_path

  def print_tree(self, limit=0.0, display_ids=None):
    """
    prints out the tree, including some formatting

    args:
      limit:       float of the minimum amount to display
      display_ids: flag to display the AWS ID after the name

    returns:
      none
    """
    limit = float(limit) or 0.0
    locale.setlocale(locale.LC_ALL, '')
    node_spend = locale.format('%.2f', self.node_spend, grouping=True)
    node_spend = '$' + str(node_spend)
    name = self.name + ':'

    if self.parent is not None:
      parent_path = self.get_parent_path()
      parent_path = ' -> '.join(parent_path)
      print(parent_path, '->', name, node_spend, self.currency)
      print('==========')
    else:
      print(name, node_spend, self.currency)

    for account in sorted(self.get_accounts(),
                          key = lambda account: account.total,
                          reverse = True):
      if account.total >= limit:
        account_spend = locale.format('%.2f', account.total, grouping=True)
        account_spend = '$' + str(account_spend)
        if display_ids:
          print('{:25}\t({})\t{} {}'.format(account.name,
                                            account.id,
                                            account_spend,
                                            account.currency))
        else:
          print('{:25}\t\t{} {}'.format(account.name,
                                        account_spend,
                                        account.currency))

    print()

    for child in self.children:
      child.print_tree(limit, display_ids)

  def csv_output(self, limit=0.0, outfile=None, month=None, year=None,
                 append=False):
    """
    output the ou-based spend to a CSV.  can create a new file, or append
    an existing one.

    for accounts that live in the ROOT OU, the lab/PI and project fields will
    be set to 'ROOT'.

    the CSV header is defined in CSV_HEADER and can be used to customize the
    field names you want to output.

    if you want to change the fields that are printed out, please update
    the list definitions of 'line' w/the variables you would like to display.

    the default settings for this reflect the way in which our lab categorizes
    projects, and may require tweaking for other types of orgs.

    args:
      limit:    only print the OU spend that's greater than this
      outfile:  name of the CSV to write to.  default is 'outfile.csv'
      month:    month of the report (gleaned from the billing CSV)
      year:     year of the report (gleaned from the billing CSV)
      append:   if False, create a new file (default).
    """
    CSV_OUTFILE = 'output.csv'
    CSV_HEADER = ['year', 'month', 'lab or PI', 'project', 'spend', 'num accounts']

    if month is None:
      print('need a month')
      sys.exit(1)

    if year is None:
      print('need a year')
      sys.exit(1)

    if outfile is None:
      outfile = CSV_OUTFILE



    limit = float(limit) or 0.0
    locale.setlocale(locale.LC_ALL, '')
    formatted_spend = locale.format('%.2f', self.node_account_spend, grouping=True)
    formatted_spend = '$' + str(formatted_spend)

    if append is False:
      with open(outfile, 'w', newline='') as csv_file:
        writer = csv.writer(csv_file, delimiter=',')
        line = CSV_HEADER
        writer.writerow(line)

    if self.node_account_spend > limit:
      if self.parent is None:
        with open(outfile, 'a', newline='') as csv_file:
          writer = csv.writer(csv_file, delimiter=',')
          line = [
            year,
            month,
            self.name,
            self.name,
            formatted_spend,
            len(self.accounts)
          ]
          writer.writerow(line)

      else:
        with open(outfile, 'a', newline='') as csv_file:
          writer = csv.writer(csv_file, delimiter=',')
          line = [
            year,
            month,
            self.parent.name,
            self.name,
            formatted_spend,
            len(self.accounts)
          ]
          writer.writerow(line)

    for child in self.children:
      child.csv_output(
        limit=limit,
        outfile=outfile,
        month=month,
        year=year,
        append=True
      )
