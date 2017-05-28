#! /usr/bin/env python
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

# AWS details - account ID and S3 bucket name are kept in a separate file in
# the local directory, "awssettings.py".  do NOT check this in to github!
#
# see also .gitignore.
#
import awssettings

# email settings:  user-defined content and server information
#
import emailsettings

def get_latest_bill(billing_file_path, save):
  """
  get the latest billing CSV from S3 (default) or a local file.
  args:
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
    billing_filename =  awssettings.AWS_S3_ACCOUNT_NUMBER + \
                        '-aws-billing-csv-' + \
                        year + '-' + month + '.csv'

    logging.debug('retrieving consolidated billing CSV from S3: ' + billing_filename)
    s3 = boto3.resource('s3')
    b = s3.Object(awssettings.AWS_S3_BUCKET_NAME, billing_filename)
    billing_data = b.get()['Body'].read().decode('utf-8')

    if not billing_data:
      print "unable to find billing data (%s) in your bucket!" % billing_filename
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

def generate_report(user_dict, limit):
  """
  generate the billing report, categorized by OU.

  args:
    - user_dict:    dict of all users and individual total spends
    - limit:        display only amounts greater then this in the report.
                    the amount still counts towards the totals.
  """
  locale.setlocale(locale.LC_ALL, '') # for comma formatting
  total_spend = 0

  project_dict = collections.defaultdict(list)
  client = boto3.client('organizations')

  # for each user, get the OU that they are the member of
  for id in user_dict.keys():
    u = user_dict[id]
    logging.debug('parsing %s %s' % (user_dict[id]['name'], id))
    ou_r = client.list_parents(ChildId=id)
    ou_id = ou_r['Parents'][0]['Id']

    # hack this for ROOT
    if ou_id == 'r-43a5':
      ou_name = 'ROOT'
    else:
      ou_name_r = client.describe_organizational_unit(OrganizationalUnitId=ou_id)
      ou_name = ou_name_r['OrganizationalUnit']['Name']

    total_spend = total_spend + u['total']
    project_dict[ou_name].append((u['name'], id, u['total'], u['currency']))

  # generate the report, broken down by project
  sum_str = locale.format('%.2f', total_spend, grouping=True)
  report = '== Current AWS totals:  $%s USD (only shown below: > $%s) ==\n\n' \
            % (sum_str, limit)

  for p in sorted(project_dict.keys()):
    report = report + "Project/Group: %s\n" % p

    subtotal = 0
    for t in sorted(project_dict[p], key = lambda t: -t[2]):
      (acct_name, acct_num, acct_total, acct_total_currency) = t
      subtotal = subtotal + acct_total
      if acct_total < limit:
        continue
      acct_total_str = locale.format("%.2f", acct_total, grouping=True)
      # report = report + "{:<25}\t({})\t{} {}\n".format(acct_name, acct_num,
      #                                                  acct_total_str,
      #                                                  acct_total_currency)
      report = report + "{:<25}\t\t{} {}\n".format(acct_name,
                                                   acct_total_str,
                                                   acct_total_currency)
    subtotal_str = locale.format("%.2f", subtotal, grouping=True)
    report = report + "Subtotal: %s\n\n" % subtotal_str

  return report

def send_email(report, weekly):
  if not weekly:
    subject = emailsettings.EMAIL_SUBJECT_MONTHLY
    preamble = emailsettings.EMAIL_PREAMBLE_MONTHLY + \
               emailsettings.EMAIL_PREAMBLE
  else:
    subject = emailsettings.EMAIL_SUBJECT_WEEKLY
    preamble = emailsettings.EMAIL_PREAMBLE_WEEKLY + \
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
download, parse and create an email report for general AWS spend.
this script is designed to run as a cron job, providing weekly
(incremental) and end-of-month billing reports.  the only difference
between these reports is the formatting of the email subject and preamble.
  """

  parser = argparse.ArgumentParser(description=desc)
  #frequency = parser.add_mutually_exclusive_group()

  parser.add_argument("-e",
                      "--email",
                      help="""
send the report as email, using the settings defined in emailsettings.py
                      """,
                      action="store_true")
  parser.add_argument("-l",
                      "--limit",
                      help="""
do not display spends less than this value in USD on the report.
default is $5.00USD.
                      """,
                      type=float,
                      default=5.0)
  parser.add_argument("-L", "--local", help="""
read a consolidated billing CSV from the filesystem and bypass
downloading from S3.
                      """,
                      type=str)
  parser.add_argument("-q",
                      "--quiet",
                      help="do not print to STDOUT.",
                      action="store_true")
  parser.add_argument("-s",
                      "--save",
                      help="save billing CSV to local directory.",
                      action="store_true")
  parser.add_argument("-w",
                      "--weekly",
                      help="""
formats the email verbiage to show the report is a weekly per-user
report on spend from the start of the current month to the present day.
this argument is default if not specified.
                      """,
                      action="store_true")
  parser.add_argument("-m",
                      "--monthly",
                      help="""
formats email subject and body to say "end of month".  typically used
for end of month reports.  use cron trickery (in the provided crontab)
to trigger the script in this way.  this argument overrides --weekly!
                      """,
                      action="store_true")

  args = parser.parse_args()

  return args

def main():
  args = parse_args()

  billing_data = get_latest_bill(args.local, args.save)
  user_dict = parse_billing_data(billing_data)
  report = generate_report(user_dict, args.limit)

  if args.email:
    send_email(report, args.weekly)

  if not args.quiet:
    print report

if __name__ == "__main__":
  main()
