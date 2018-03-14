#! /usr/bin/env python3
#
# aws-audit.py
#
# download, parse and create an email report for general AWS spend
#
# this script is designed to run as a cron job, providing weekly (incremental)
# and end-of-month billing reports.  the only difference between these reports
# is the formatting of the email subject and preamble.
#
import argparse
import boto3
from botocore.exceptions import ClientError
import collections
import csv
import datetime
from email.mime.text import MIMEText
from io import StringIO
import locale
import logging
import smtplib
import socket
import sys

# support for N-ary tree data structure to support OUs
import tree

logging.basicConfig(level=logging.WARN, format='%(asctime)s - %(levelname)s - %(message)s')

# email settings:  user-defined content and server information
#
import emailsettings

def get_latest_bill(aws_id, billing_bucket, billing_file_path, save):
  """
  get the latest billing CSV from S3 (default) or a local file.
  args:
    aws_id:             AWS account number
    billing_bucket:     name of the billing bucket
    billing_file_path:  full path to consolidated billing file on a local
                        FS (optional)
    save:               save the CSV to disk with the default filename

  returns:
    csv object of billing data
  """
  if billing_file_path:
    logging.debug('opening local consolidated billing CSV for reading: ' \
                  + billing_file_path)
    f = open(billing_file_path, 'r')
    billing_data = f.read()
  else:
    today = datetime.date.today()
    month = today.strftime('%m')
    year = today.strftime('%Y')
    billing_filename =  aws_id + '-aws-billing-csv-' + \
                        year + '-' + month + '.csv'

    logging.debug('retrieving consolidated billing CSV from S3: ' + billing_filename)
    s3 = boto3.resource('s3')
    b = s3.Object(billing_bucket, billing_filename)
    billing_data = b.get()['Body'].read().decode('utf-8')

    if not billing_data:
      print("unable to find billing data (%s) in your bucket!" % billing_filename)
      sys.exit(-1)

  if (save):
    f = open(billing_filename, 'w')
    f.write(billing_data)
    f.close

  return csv.reader(billing_data.split('\n'))

def parse_billing_data(billing_data):
  """
  parse the billing data and store it in a hash

  args:
    billing_data:  CSV object of billing data

  returns:
    user_dict:  dict, keyed by AWS ID, containing name, user total for all
                services, and currency
  """
  user_dict = collections.defaultdict(dict)

  for row in billing_data:
    if len(row) < 4:
      continue
    if row[3] == 'AccountTotal':
      acct_num = row[2]
      user_dict[acct_num]['name'] = row[9]
      user_dict[acct_num]['total'] = float(row[24])
      user_dict[acct_num]['currency'] = row[23]

  return user_dict

def get_root_ou_id(aws_id):
  # TODO: use collections.namedtuple
  """
  get the ID of the ROOT OU

  args:
    aws_id:  AWS account number

  returns:
    ou_id:   tuple containing ID number of the ROOT OU and 'ROOT'
  """
  client = boto3.client('organizations')
  ou_r = client.list_roots()

  return (ou_r['Roots'][0]['Id'], 'ROOT')

def get_ou_children(ou_id):
  # TODO: use collections.namedtuple
  """
  get the list of OU children for a given OU id

  args:
    ou_id:  ID number of the current OU

  returns:
    children:  list of tuples containing children OU IDs and descriptive
               name, or NoneType
  """
  client = boto3.client('organizations')
  ou_r = client.list_organizational_units_for_parent(ParentId=ou_id)

  children = list()
  while True:
    for ou in ou_r['OrganizationalUnits']:
      children.append((ou['Id'], ou['Name']))
    if 'NextToken' in ou_r:
      ou_r = client.list_organizational_units_for_parent(
          ParentId=ou_id, NextToken=ou_r['NextToken'])
    else:
      break
  return children or None

def get_accounts_for_ou(ou_id):
  # TODO: use collections.namedtuple
  """
  get the accounts attached to a given ou_id

  args:
    ou_id:  ID number of an OU

  returns:
    accounts: list of tuples containing AWS ID and full name
  """
  client = boto3.client('organizations')
  ou_r = client.list_accounts_for_parent(ParentId=ou_id)
  accounts = list()

  while True:
    for acct in ou_r['Accounts']:
      accounts.append((acct['Id'], acct['Name']))
    if 'NextToken' in ou_r:
      ou_r = client.list_accounts_for_parent(ParentId=ou_id,
                                             NextToken=ou_r['NextToken'])
    else:
      break
  return accounts

def init_tree(aws_id):
  """
  initializes the OU tree datastructure

  args:
    aws_id:  the AWS ID of the root consolidated billing account

  returns:
    root Node object
  """
  root_ou = get_root_ou_id(aws_id)
  root = tree.Node(id=root_ou[0], name=root_ou[1])

  return root

def populate_tree(tree, user_dict):
  """
  populates the OU-based tree, mapping account/OU to billing data.  if users
  are in the bill, but not in the AWS org (due to leaving), the left-over
  accounts are returned.

  args:
    tree:  root node object
    user_dict:  dict created from parsing billing file

  returns:
    user_dict:  dict containing left-over users
  """
  current_node = tree
  children = get_ou_children(current_node.id)

  accounts = get_accounts_for_ou(current_node.id)
  if accounts:
    for id, name in accounts:
      if id not in user_dict:
        # account has zero spend!
        current_node.add_account((id, name, 0.0))
      else:
        total = user_dict[id]['total']
        currency = user_dict[id]['currency']
        current_node.add_account((id, name, total, currency))
        #del user_dict[id]

  if children is not None:
    for id, name in children:
      current_node.add_child(id=id, name=name)
    for child in current_node.children:
      populate_tree(child, user_dict)

  return user_dict

def generate_simple_report(user_dict, limit, display_ids):
  """
  generate the billing report, categorized by OU.

  args:
    user_dict:    dict of all users and individual total spends
    limit:        display only amounts greater then this in the report.
                  the amount still counts towards the totals.
    display_ids:  display each user's AWS ID after their name
    full:         boolean.  generate a full report.
  """
  locale.setlocale(locale.LC_ALL, '') # for comma formatting
  total_spend = 0
  report = ''
  account_details = list()

  # for each user, get the OU that they are the member of
  for id in user_dict.keys():
    u = user_dict[id]
    total_spend = total_spend + u['total']
    account_details.append((u['name'], id, u['total'], u['currency']))

  sum_str = locale.format('%.2f', total_spend, grouping=True)
  report = report + \
           '== Current AWS totals:  $%s USD (only shown below: > $%s) ==\n\n' \
           % (sum_str, limit)

  for acct in sorted(account_details, key = lambda acct: -acct[2]):
    (acct_name, acct_num, acct_total, acct_total_currency) = acct

    if acct_total < limit:
      continue

    acct_total_str = locale.format("%.2f", acct_total, grouping=True)
    if display_ids:
      report = report + "{:<25}\t({})\t{} {}\n".format(acct_name, acct_num,
                                                       acct_total_str,
                                                       acct_total_currency)
    else:
      report = report + "{:<25}\t\t${} {}\n".format(acct_name,
                                                    acct_total_str,
                                                    acct_total_currency)

  return report

def send_email(report, weekly):
  """
  send the report as an email, with the to:, from:, subject: and preamble
  defined in emailsettings.py.

  args:
    report:  the raw string containing the final report
    weekly:  boolean, if true use weekly email formatting.  if false, use
               monthly.
  """
  if weekly:
    subject = emailsettings.EMAIL_SUBJECT_WEEKLY
    preamble = emailsettings.EMAIL_PREAMBLE_WEEKLY + \
               emailsettings.EMAIL_PREAMBLE
  else:
    subject = emailsettings.EMAIL_SUBJECT_MONTHLY
    preamble = emailsettings.EMAIL_PREAMBLE_MONTHLY + \
               emailsettings.EMAIL_PREAMBLE

  report = preamble + report + "\n\n---\nSent from %s.\n" % \
           (socket.gethostname())

  msg = MIMEText(report)
  msg['Subject'] = subject
  msg['From'] = emailsettings.EMAIL_FROM_ADDR
  msg['To'] = emailsettings.EMAIL_TO_ADDR

  s = smtplib.SMTP(emailsettings.MAIL_SERVER)
  s.sendmail(emailsettings.EMAIL_FROM_ADDR,
             [emailsettings.EMAIL_TO_ADDR],
             msg.as_string())

def parse_args():
  desc = """
Download, parse and create reports for general AWS spend, optionally
sending the report as an e-mail.
  """
  epil = """
Please refer to README.md for more detailed usage instructions and examples.
  """

  parser = argparse.ArgumentParser(description=desc, epilog=epil)

  # AWS settings
  parser.add_argument("-i",
                      "--id",
                      help="""
AWS account ID for consolidated billing.  Required unless using the --local
argument.
                      """,
                      type=str,
                      metavar="AWS_ID")
  parser.add_argument("-b",
                      "--bucket",
                      help="""
S3 billing bucket name.  Required unless using the --local argument.
                      """,
                      type=str,
                      metavar="S3_BILLING_BUCKET")
  parser.add_argument("-L",
                      "--local",
                      help="""
Read a consolidated billing CSV from the filesystem and bypass
downloading from S3.
                      """,
                      type=str,
                      metavar="LOCAL_BILLING_CSV")
  parser.add_argument("-s",
                      "--save",
                      help="Save the billing CSV to the local directory.",
                      action="store_true")

  # output formatting
  parser.add_argument("-q",
                      "--quiet",
                      help="Do not print to STDOUT.",
                      action="store_true")
  parser.add_argument('-o',
                      "--ou",
                      help="""
Use AWS Organizational Units to group users.  This option will greatly increase
the amount of time it takes the script to run.  If this option is specified,
but no OUs have been defined for this consolidated billing group, the script
will still run successfully but will take much longer to complete.
                      """,
                      action="store_true")
  parser.add_argument("-l",
                      "--limit",
                      help="""
Do not display spends less than this value in USD on the report.  Any spends
not displayed will still be counted towards all totals.  Default is $5.00USD.
                      """,
                      type=float,
                      default=5.0)
  parser.add_argument("-D",
                      "--display_ids",
                      help="Display AWS account IDs in the report.",
                      action="store_true")
  parser.add_argument("-f",
                      "--full",
                      help="""
Generate a full report.  This option is only useful when using OUs in
a consolidated billing setting, and the --ou option is used.  An additional
section is added at the end of the original report that lists all users sorted
by spend.  If the --ou argument is not set, this will be ignored.
                      """,
                      action="store_true")
  parser.add_argument("-e",
                      "--email",
                      help="""
Send the report as an email, using the settings defined in emailsettings.py.
                      """,
                      action="store_true")

  frequency = parser.add_mutually_exclusive_group()
  frequency.add_argument("-w",
                         "--weekly",
                         help="""
Formats the email subject and body to deonte a "weekly" report on spend,
from the start of the current month to the present day.
                         """,
                         action="store_true")
  frequency.add_argument("-m",
                         "--monthly",
                         help="""
Formats the email subject and body to denote an "end of month" report.
                         """,
                         action="store_true")

  args = parser.parse_args()

  return args

def main():
  args = parse_args()

  if args.full and not args.ou:
    args.full = False

  if args.id is None and args.local is None:
    print("Please specify an AWS account id with the --id argument, " +
          "unless reading in a local billing CSV with --local <filename>.")
    sys.exit(-1)

  if args.bucket is None and args.local is None:
    print("Please specify a S3 billing bucket name with the --bucket " +
          "argument, unless reading in a local billing CSV with --local " +
          "<filename>.")
    sys.exit(-1)

  if args.email and (not args.weekly and not args.monthly):
    print("Please specify the frequency formatting of the email using " +
          "--weekly or --monthly")
    sys.exit(-1)

  report = ''
  billing_data = get_latest_bill(args.id, args.bucket, args.local, args.save)
  user_dict = parse_billing_data(billing_data)

  # no OU tree, just spew out the report
  if not args.ou:
    report = generate_simple_report(user_dict, args.limit, args.display_ids)

  else:
    root = init_tree(args.id)
    populate_tree(root, user_dict)
    sum_str = locale.format('%.2f', root.node_spend, grouping=True)
    report = report + \
           '== Current AWS totals:  $%s USD (only shown below: > $%s) ==\n\n' \
           % (sum_str, args.limit)

    old_stdout = sys.stdout
    tree_output = StringIO()
    sys.stdout = tree_output

    root.print_tree(limit=args.limit, display_ids=args.display_ids)

    sys.stdout = old_stdout
    report = report + tree_output.getvalue()

    # add the basic report to the end if desired
    if args.full:
      report = report + '\n\n'
      report = report + generate_simple_report(user_dict, args.limit,
                                               args.display_ids)

  if not args.quiet:
    print(report)

  if args.email:
    send_email(report, args.weekly)

if __name__ == "__main__":
  main()
