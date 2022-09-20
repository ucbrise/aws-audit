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
import collections
import csv
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from io import StringIO
import locale
import os
import smtplib
import socket
import sys

# basic config import (namedtuple setup)
import config

# common aws utilities
import awslib

# support for N-ary tree data structure to support OUs
import tree

# email settings:  user-defined content and server information
import emailsettings

locale.setlocale(locale.LC_ALL, '') # for comma formatting

def parse_billing_data(billing_data):
  """
  parse the billing data and store it in a hash

  args:
    billing_data:  CSV object of billing data

  returns:
    user_dict:  dict, keyed by AWS ID, containing name, user total for all
                services, and currency
    currency:   string, currency used (ie: USD)
    month:      billing month (for CSV output)
    year:       billing year  (for CSV output)
  """
  user_dict = collections.defaultdict(dict)
  currency = ''
  month = ''
  year = ''

  billing_data = list(billing_data)
  # populate the dict of user spends
  for row in billing_data:
    if len(row) < 4:
      continue
    if row[3] == 'AccountTotal':
      if not currency:
        currency = row[23]

      if not month or not year:
        date = row[6]
        month = date[5:7]
        year = date[0:4]

      acct_num = row[2]
      user_dict[acct_num]['name'] = row[9]
      user_dict[acct_num]['total'] = float(row[24])
      user_dict[acct_num]['currency'] = row[23]

  # now apply any credits received (for things like compromised accounts)
  for row in billing_data:
    if len(row) < 4:
      continue
    if row[3] == 'LinkedLineItem' and 'Unauthorized Usage' in row[18]:
      # value is always negative, so add!
      user_dict[row[2]]['total'] = user_dict[row[2]]['total'] + float(row[25])

  return user_dict, currency, month, year

def init_tree(aws_id, default_currency):
  """
  initializes the OU tree datastructure

  args:
    aws_id:  the AWS ID of the root consolidated billing account
    default_currency:  the default currency

  returns:
    root Node object
  """
  root_ou = awslib.get_root_ou_id(aws_id)
  root = tree.Node(id=root_ou.id, name=root_ou.name, currency=default_currency)

  return root

def populate_tree(tree, user_dict, default_currency):
  """
  populates the OU-based tree, mapping account/OU to billing data.  if users
  are in the bill, but not in the AWS org (due to leaving), the left-over
  accounts are returned.

  args:
    tree:              root node object
    user_dict:         dict created from parsing billing file
    default_currency:  the default currency pulled from the billing CSV
  """
  current_node = tree
  children = awslib.get_ou_children(current_node.id)
  accounts = awslib.get_accounts_for_ou(current_node.id)

  if accounts:
    for account in accounts:
      if account.id not in user_dict:
        # account has zero spend and not showing up in the billing CSV
        current_node.add_account(config.AccountInfo(
          id=account.id,
          name=account.name,
          total=0.0,
          currency=default_currency)
        )
      else:
        current_node.add_account(config.AccountInfo(
          id=account.id,
          name=account.name,
          total=user_dict[account.id]['total'],
          currency=user_dict[account.id]['currency'])
         )

  if children is not None:
    for child in children:
      current_node.add_child(
        id=child.id,
        name=child.name,
        currency=default_currency
      )
    for child in current_node.children:
      populate_tree(
        child,
        user_dict,
        default_currency
      )

def add_leavers(root, user_dict, default_currency):
  """
  find AWS accounts that have spend in the billing CSV, but are not in the
  consolidated billing family.  create a top-level node containing these
  users and their spend.

  args:
    root:       the root Node of the entire OU tree
    user_dict:  the user dict generated from the billing CSV
    default_currency:  the default currency
  """
  leavers_node_added = False
  aws_accounts = awslib.get_accounts_for_org()

  for id in user_dict.keys():
    if id not in aws_accounts:
      if not leavers_node_added:
        leavers_node_added = True
        leavers_node = root.add_child(id='leavers',
                                      name='No Longer in AWS Organization',
                                      currency=default_currency
        )

      leavers_node.add_account(config.AccountInfo(
        id=id,
        name=user_dict[id]['name'],
        total=user_dict[id]['total'],
        currency=user_dict[id]['currency'])
      )

def generate_simple_csv(user_dict, outfile=None, limit=0.0,
                        month=None, year=None):
  """
  output account-based spends to a CSV.  can create a new file, or append to an
  existing one.

  the CSV header is defined in CSV_HEADER and can be used to customize the
  field names you want to output.

  if you want to change the fields that are printed out, please update
  the list definitions of 'line' w/the variables you would like to display.

  the default settings for this reflect the way in which our lab categorizes
  projects, and may require tweaking for other types of orgs.

  args:
    limit:    only print the OU spend that's greater than this
    outfile:  name of the CSV to write to.
    month:    month of the report (gleaned from the billing CSV)
    year:     year of the report (gleaned from the billing CSV)
  """
  CSV_HEADER = ['year', 'month', 'person', 'spend']
  account_details = list()
  limit = float(limit) or 0.0
  locale.setlocale(locale.LC_ALL, '')

  if os.path.isfile(outfile):
    append = True
  else:
    append = False

  # add the header to the CSV if we're creating it
  if append is False:
    with open(outfile, 'w', newline='') as csv_file:
      writer = csv.writer(csv_file, delimiter=',')
      writer.writerow(CSV_HEADER)

  # for each user, get the OU that they are the member of
  for id in user_dict.keys():
    u = user_dict[id]
    account_details.append((u['name'], id, u['total'], u['currency']))

  for acct in sorted(account_details, key = lambda acct: acct[2], reverse = True):
    (acct_name, acct_num, acct_total, acct_total_currency) = acct

    if acct_total < limit:
      continue

    acct_total_str = locale.format("%.2f", acct_total, grouping=True)
    acct_total_str = '$' + str(acct_total_str)

    with open(outfile, 'a', newline='') as csv_file:
      writer = csv.writer(csv_file, delimiter=',')
      line = [year, month, acct_name, acct_total_str]
      writer.writerow(line)

def generate_leaderboard(user_dict, display_ids, top, default_currency):
  """
  list top N spenders

  args:
    user_dict:         dict of all users and individual total spends
    display_ids:       display each user's AWS ID after their name
    default_currency:  default currency
    top_users:         limit output to N top users.  if 0, print all.
  """
  total_spend = 0
  report = ''
  account_details = list()
  top_spenders = list()

  # for each user, get the OU that they are the member of
  for id in user_dict.keys():
    u = user_dict[id]
    account_details.append((u['name'], id, u['total'], u['currency']))

  top_spenders = sorted(account_details, key = lambda acct: acct[2], reverse = True)[:top]
  total_spend = sum([x[2] for x in top_spenders])

  sum_str = locale.format('%.2f', total_spend, grouping=True)
  report = "== AWS top %s leaderboard:  $%s %s ==\n\n" \
           % (top, sum_str, default_currency)

  for acct in top_spenders:
    (acct_name, acct_num, acct_total, acct_total_currency) = acct

    acct_total_str = locale.format("%.2f", acct_total, grouping=True)
    if display_ids:
      report = report + "{:<25}\t({})\t{} {}\n".format(acct_name, acct_num,
                                                       acct_total_str,
                                                       acct_total_currency)
    else:
      report = report + "{:<25}\t\t${} {}\n".format(acct_name,
                                                    acct_total_str,
                                                    acct_total_currency)

  report = report + "\n\n"

  return report

def generate_simple_report(user_dict, limit, display_ids, default_currency):
  """
  generate the billing report, categorized by OU.

  args:
    user_dict:         dict of all users and individual total spends
    limit:             display only amounts greater then this in the report.
                       default is 0 (all accounts shown)
    display_ids:       display each user's AWS ID after their name
    default_currency:  default currency
  """
  total_spend = 0
  report = ''
  account_details = list()

  # for each user, get the OU that they are the member of
  for id in user_dict.keys():
    u = user_dict[id]
    total_spend = total_spend + u['total']
    account_details.append((u['name'], id, u['total'], u['currency']))

  sum_str = locale.format('%.2f', total_spend, grouping=True)
  report = "== Current AWS totals:  $%s %s (only shown below: > $%s) ==\n\n" \
           % (sum_str, default_currency, limit)

  for acct in sorted(account_details, key = lambda acct: acct[2], reverse = True):
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

def create_plots(acctcsv=None, orgcsv=None):
  """
  create plots based on existing CSV data, and save them to the local FS.

  args:
    acctcsv:  full path to the account-based spends CSV
    orgcsv:   full path to the org-based spends CSV

  returns:
    tuple of the full path to the plots created, or None
  """
  import plots  # slow import is slow

  account_plot = org_plot = None

  if acctcsv is not None:
    outfile = os.path.splitext(acctcsv)[0]
    account_plot = plots.account_spend_plot(csvfile=acctcsv, outputfilename=outfile)

  if orgcsv is not None:
    outfile = os.path.splitext(orgcsv)[0]
    org_plot = plots.org_spend_plot(csvfile=orgcsv, outputfilename=outfile)

  return account_plot, org_plot

def send_email(report, weekly, plots):
  """
  send the report as an email, with the to:, from:, subject: and preamble
  defined in emailsettings.py.

  args:
    report:  the raw string containing the final report
    weekly:  boolean, if true use weekly email formatting.  if false, use
               monthly.
    plots:   a tuple of plot file locations to attach to the email
  """
  account_plot, org_plot = plots

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
  message_body = MIMEText(report)

  msg = MIMEMultipart()
  msg['Subject'] = subject
  msg['From'] = emailsettings.EMAIL_FROM_ADDR
  msg['To'] = emailsettings.EMAIL_TO_ADDR
  msg.attach(message_body)

  if account_plot:
    img_data = open(account_plot, 'rb').read()
    image = MIMEImage(img_data, name=os.path.basename(account_plot))
    msg.attach(image)

  if org_plot:
    img_data = open(org_plot, 'rb').read()
    image = MIMEImage(img_data, name=os.path.basename(org_plot))
    msg.attach(image)

  s = smtplib.SMTP(emailsettings.MAIL_SERVER)
  s.sendmail(emailsettings.EMAIL_FROM_ADDR,
             [emailsettings.EMAIL_TO_ADDR],
             msg.as_string())

def parse_args():
  desc = """
Download, parse and create reports for general AWS spend, optionally
sending the report as an e-mail and/or output CSV-based spending data.
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
Do not display spends less than this value on the report.  Any spends not
displayed will still be counted towards all totals.  Default is 5.00.
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
by spend.  If the --ou argument is not set, this option will be ignored.
                      """,
                      action="store_true")
  parser.add_argument("-e",
                      "--email",
                      help="""
Send the report as an email, using the settings defined in emailsettings.py.
                      """,
                      action="store_true")
  parser.add_argument("-O",
                      "--orgcsv",
                      help="""
Output org/project-based spends to a CSV.  If FILENAME exists, the script
will append to the file instead of creating a new one.
                      """,
                      type=str,
                      metavar="FILENAME")
  parser.add_argument("-C",
                      "--csv",
                      help="""
Output account-based spends to a CSV.  If FILENAME exists, the script
will append to the file instead of creating a new one.
                      """,
                      type=str,
                      metavar="FILENAME")
  parser.add_argument("-p",
                      "--plot",
                      help="""
Create plots of CSV data.  Only useful if the --csv or --orgcsv arguments
are used.  This will create PNG plots that are saved in the directory where
the CSV data lives, and will share the filename of the CSV file used to create
the plot.  If this argument is specified with the --email argument, any images
will be attached to the resulting message.
                      """,
                      action="store_true")
  parser.add_argument("-T",
                      "--top",
                      help="""
Display the top N spenders at the beginning of the report.  0 (default) will
ignore this argument.
                      """,
                      type=int,
                      default=0)

  # monthly or weekly style email reports
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

  if args.id is None and args.local is None:
    print("Please specify an AWS account id with the --id argument, " +
          "unless reading in a local billing CSV with --local <filename>.")
    sys.exit(-1)

  if args.bucket is None and args.local is None:
    print("Please specify a S3 billing bucket name with the --bucket " +
          "argument, unless reading in a local billing CSV with --local " +
          "<filename>.")
    sys.exit(-1)

  if args.id is None and args.ou is not None:
    print("You must supply an AWS account id with the --id argument when " +
          "using the --ou argument.")
    sys.exit(-1)

  if args.email and (not args.weekly and not args.monthly):
    print("Please specify the frequency formatting of the email using " +
          "--weekly or --monthly")
    sys.exit(-1)

  if args.orgcsv and not args.ou:
    print("You must specify the --ou argument to use the --orgcsv option.")
    sys.exit(-1)

  if args.csv or args.orgcsv:
    if args.csv == args.orgcsv:
      print("Please use different filenames for the --csv and --orgcsv options.")
      sys.exit(-1)

  if args.plot and (not args.csv or not args.orgcsv):
    print("You must specify at least one CSV file to plot with the --csv or " +
          " --orgcsv options.")
    sys.exit(-1)

  report = ''
  billing_data = awslib.get_latest_bill(
    args.id,
    args.bucket,
    args.local,
    args.save
  )
  user_dict, currency, month, year = parse_billing_data(billing_data)

  # leaderboard?
  if args.top != 0:
    report = generate_leaderboard(
      user_dict,
      args.display_ids,
      args.top,
      currency
    )

  # no OU tree, just spew out the report
  if not args.ou:
    report = report + generate_simple_report(
      user_dict,
      args.limit,
      args.display_ids,
      currency
    )

  # use the OU tree, more complex report
  else:
    root = init_tree(args.id, currency)
    populate_tree(root, user_dict, currency)

    # handle those who have left the org, but are in the billing CSV.
    add_leavers(root, user_dict, currency)

    sum_str = locale.format('%.2f', root.node_spend, grouping=True)
    report = report + \
           '== Current AWS totals:  $%s %s (only shown below: > $%s) ==\n\n' \
           % (sum_str, currency, args.limit)

    old_stdout = sys.stdout
    tree_output = StringIO()
    sys.stdout = tree_output

    root.print_tree(limit=args.limit, display_ids=args.display_ids)

    sys.stdout = old_stdout
    report = report + tree_output.getvalue()

    # add the basic report to the end if desired
    if args.full:
      report = report + '\n\n'
      report = report + generate_simple_report(
        user_dict,
        args.limit,
        args.display_ids,
        currency
      )

  if args.csv:
    generate_simple_csv(user_dict, outfile=args.csv, month=month, year=year)

  if args.orgcsv:
    root.generate_project_csv(outfile=args.orgcsv, month=month, year=year)

  account_plot = org_plot = None
  if args.plot:
    account_plot, org_plot = create_plots(acctcsv=args.csv, orgcsv=args.orgcsv)

  if not args.quiet:
    print(report)

  if args.email:
    send_email(report, args.weekly, (account_plot, org_plot))

if __name__ == "__main__":
  main()
