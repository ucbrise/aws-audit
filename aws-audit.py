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
import locale
import logging
import smtplib
import socket
import sys

logging.basicConfig(level=logging.WARN, format='%(asctime)s - %(levelname)s - %(message)s')

# email settings:  user-defined content and server information
#
import emailsettings

def get_latest_bill(aws_id, billing_bucket, billing_file_path, save):
  """
  get the latest billing CSV from S3 (default) or a local file.
  args:
    - aws_id:             AWS account number
    - billing_bucket:     name of the billing bucket
    - billing_file_path:  full path to consolidated billing file on a local
                          FS (optional)
    - save:               save the CSV to disk with the default filename

  returns:
    - csv object of billing data
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
  parse the billing data, store it in a hash and calculate total spend.

  args:
    - billing_data:  CSV object of billing data

  returns:
    - user_dict:  dict, keyed by AWS ID, containing name, user total for all
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

def generate_report(user_dict, limit, display_ids, use_ou, full):
  """
  generate the billing report, categorized by OU.

  args:
    - user_dict:    dict of all users and individual total spends
    - limit:        display only amounts greater then this in the report.
                    the amount still counts towards the totals.
    - display_ids:  display each user's AWS ID after their name
    - full:         boolean.  generate a full report.
  """
  locale.setlocale(locale.LC_ALL, '') # for comma formatting
  total_spend = 0
  report = ''
  project_dict = collections.defaultdict(list)

  # for each user, get the OU that they are the member of
  for id in user_dict.keys():
    u = user_dict[id]
    logging.debug('parsing %s %s' % (u['name'], id))

    if use_ou:
      ou_name = get_ou_name(id)
    else:
      ou_name = 'ROOT'

    total_spend = total_spend + u['total']
    project_dict[ou_name].append((u['name'], id, u['total'], u['currency']))

  sum_str = locale.format('%.2f', total_spend, grouping=True)
  if (full and use_ou) or (not full and not use_ou) or (use_ou and not full):
    report = report + \
             '== Current AWS totals:  $%s USD (only shown below: > $%s) ==\n\n' \
             % (sum_str, limit)
  else:
    full = False # so we always skip the last if statement
    report = report + '\n\n'

  for p in sorted(project_dict.keys()):
    report = report + "Project/Group: %s\n" % p

    subtotal = 0
    for t in sorted(project_dict[p], key = lambda t: -t[2]):
      (acct_name, acct_num, acct_total, acct_total_currency) = t
      subtotal = subtotal + acct_total
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

    subtotal_str = locale.format("%.2f", subtotal, grouping=True)
    report = report + "Subtotal: $%s USD\n\n" % subtotal_str

  if full:
    use_ou = False
    report = report + "== All accounts, sorted by spend: =="
    report = report + generate_report(user_dict, limit, display_ids, use_ou, full)

  return report

def get_ou_name(id):
  """
  get the name of the OU an account belongs to.

  args:
    - id:  AWS id

  returns:
    - ou_name:  string containing the name of the OU
  """
  client = boto3.client('organizations')

  # handle accounts going away -- dump them in ROOT by default
  try:
    ou_r = client.list_parents(ChildId=id)
    ou_id = ou_r['Parents'][0]['Id']
  except ClientError as e:
    if e.response['Error']['Code'] == 'ChildNotFoundException':
      return 'ROOT'
    else:
      raise e

  # handle the case of an OU's parent being root.
  try:
    ou_name_r = client.describe_organizational_unit(OrganizationalUnitId=ou_id)
    ou_name = ou_name_r['OrganizationalUnit']['Name']
  except ClientError as e:
    if e.response['Error']['Code'] == 'InvalidInputException':
      ou_name = 'ROOT'
    else:
      raise e

  return ou_name

def send_email(report, weekly):
  """
  send the report as an email, with the to:, from:, subject: and preamble
  defined in emailsettings.py.

  args:
    - report:  the raw string containing the final report
    - weekly:  boolean, if true use weekly email formatting.  if false, use
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

  billing_data = get_latest_bill(args.id, args.bucket, args.local, args.save)
  user_dict = parse_billing_data(billing_data)
  report = generate_report(user_dict, args.limit, args.display_ids,
                           args.ou, args.full)

  if not args.quiet:
    print(report)

  if args.email:
    send_email(report, args.weekly)

if __name__ == "__main__":
  main()
