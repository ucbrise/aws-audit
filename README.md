# aws-audit.py

A script that will download an AWS consolidated bill, and parse out spending.

## Installation
You need to have python 3 and the latest version of boto3 installed via your
package manager of choice.

I recommend anaconda python: https://www.continuum.io/downloads

## Setup
First, your root consolidated billing account needs to be set up to receive
billing reports and save them in an S3 folder.  More details on how to set
this up are [here](http://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/billing-reports-gettingstarted-s3.html)

It is also strongly recommended to use an IAM role that has permission to
access this S3 bucket, rather than the root account itself.

Your AWS credentials need to be in a location that boto3 can discover.  More
details on how to configure AWS credentials are [here]
(https://boto3.readthedocs.io/en/latest/guide/configuration.html#configuring-credentials).

If the reports will be sent via a cronjob, please take look at
`awsreport-crontab` for ideas.

If you want to send email reports, please edit `emailsettings.py` and change the following
variables:
```
MAIL_SERVER = "localhost"
EMAIL_TO_ADDR = "list@example.corp"
EMAIL_FROM_ADDR = "Your Corp's AWS Czar <aws-watcher@@example.corp>"
```

You can also modify the subjects and preambles.

AWS [Organizational Units](http://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_ous.html)
can be used to categorize your spends.  After this has been set up in your root
accounts billing page, just add the `--ou` flag to the script when run.

## Usage
Print out the help message and exit:
`aws-audit.py --help`

This will grab the most recent bill from S3, save a copy locally, and dump the
report to STDOUT using OUs and showing account IDs:
`aws-audit.py -i <AWS_ID> -b <BILLING_BUCKET> --save --ou --display_ids`

Create a report on a downloaded billing CSV, not using OUs:
`aws-audit.py --local <LOCAL_BILLING_CSV>`

Grab the most recent bill from S3 and email a report with OUs using the monthly
template:
`aws-audit.py -i <AWS_ID> -b <BILLING_BUCKET> --ou --email --monthly`
