# email server and content settings
#
import datetime
TODAY = datetime.date.today()
DAY = TODAY.strftime('%d')
MONTH = TODAY.strftime('%m')
MONTH_NAME = TODAY.strftime('%B')
YEAR = TODAY.strftime('%Y')

MAIL_SERVER = "localhost"
EMAIL_TO_ADDR = "list@example.corp"
EMAIL_FROM_ADDR = "Your Corp's AWS Czar <aws-watcher@@example.corp>"

# email subject and preambles for weekly and monthly reports
#
EMAIL_SUBJECT_WEEKLY = "AWS Incremental Totals for %s %s (READ THIS)" \
% (MONTH_NAME, YEAR)

EMAIL_SUBJECT_MONTHLY = "AWS End-of-Month Totals for %s %s (READ THIS)" \
% (MONTH_NAME, YEAR)

EMAIL_PREAMBLE_WEEKLY = """
Incremental totals for this month's AWS usage, from the 1st through
today (%s/%s/%s).

""" % (MONTH, DAY, YEAR)

EMAIL_PREAMBLE_MONTHLY = """
Final AWS totals for the month of %s, %s.

""" % (MONTH_NAME, YEAR)

EMAIL_PREAMBLE = """
Please review your AWS usage below and confirm it matches your expectations.

Note: AWS EC2 instances cost something whenever they "run", so, shutdown or
terminate instances when you finish with them so that they do not run any
longer than necessary.  Consider using Spot Instances.

"""
