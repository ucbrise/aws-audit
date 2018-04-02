# aws-audit.py

Easily generate billing reports for organizations that use AWS [Consolidated Billing](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/consolidated-billing.html).

By default, the script output will display a list of accounts, sorted by spend.
If you use [Organizational Units](https://docs.aws.amazon.com/organizations/latest/userguide/orgs_introduction.html),
you can set the output to list the OUs and spend for each project.

Example (no-OU) output:

```
Current AWS totals:  $2,258.13 USD (only shown below: > $5.0)

User 1                   		$1,234.56
User 2                   		$789.01
User 3                   		$234.56
```

Example (with OU) output:

```
Current AWS totals:  $10,544.34 USD (only shown below: > $5.0)

ROOT: $10,544.34 USD

ROOT -> Organization 1: $2258.13 USD
==========
User 1                   		$1,234.56
User 2                   		$789.01

ROOT -> Organization 1 -> Project 1: $234.56 USD
==========
User 3                   		$234.56

ROOT -> Organization 2: $8,286.21 USD
==========
User 4                   		$2,468.02
User 5                   		$12.34

ROOT -> Organization 2 -> Project 1: $3.50 USD
==========

ROOT -> Organization 2 -> Project 2: $5,802.35 USD
==========
User 8                   		$5,678.90
User 9                   		$123.45

ROOT -> Organization 2 -> Project 3: $0.00 USD
==========
```

Notes about OU-based output:
* Each OU's spend is a sum of all children (accounts) spends
* All OUs, even those w/zero spend, are displayed

## Installation
You need to have python 3 and the latest version of boto3 installed via your
package manager of choice.

## Setup
First, your root consolidated billing account needs to be set up to receive
billing reports and save them in an S3 folder.  More details on how to set
this up are [here](http://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/billing-reports-gettingstarted-s3.html)

It is also strongly recommended to use an IAM role that has permission to
access this S3 bucket, rather than the root account itself.

Your AWS credentials need to be in a location that boto3 can discover.  Please
refer to the [boto3 documentation on configuring credentials](https://boto3.readthedocs.io/en/latest/guide/configuration.html#configuring-credentials).

If the reports will be sent via a cronjob, please take look at
`awsreport-crontab` for ideas.

If you want to send email reports, please edit `emailsettings.py` and change the following
variables:
```
MAIL_SERVER = "localhost"
EMAIL_TO_ADDR = "list@example.corp"
EMAIL_FROM_ADDR = "Your Corp's AWS Czar <aws-watcher@example.corp>"
```

You can also modify the email subject(s) and preamble(s).

AWS [Organizational Units](http://docs.aws.amazon.com/organizations/latest/userguide/orgs_manage_ous.html)
can be used to categorize your spends.  After this has been set up in your root
accounts billing page, just add the `--ou` flag to the script when run.

## Usage
Print out the help message and exit:
`aws-audit.py --help`

This will grab the most recent bill from S3, save a copy locally, and dump the
report to STDOUT using OUs and showing account IDs:
`aws-audit.py -i <AWS_ID> -b <BILLING_BUCKET> --save --ou --display_ids`

Create a report on a downloaded billing CSV, not using OUs, only displaying
spends great than $5.00:
`aws-audit.py --local <LOCAL_BILLING_CSV> --limit 5.0`

Grab the most recent bill from S3 and email a report with OUs using the monthly
template:
`aws-audit.py -i <AWS_ID> -b <BILLING_BUCKET> --ou --email --monthly`

Full output of `--help`:
```
$ ./aws-audit.py --help
usage: aws-audit.py [-h] [-i AWS_ID] [-b S3_BILLING_BUCKET]
                    [-L LOCAL_BILLING_CSV] [-s] [-q] [-o] [-l LIMIT] [-D] [-f]
                    [-e] [-w | -m]

Download, parse and create reports for general AWS spend, optionally sending
the report as an e-mail.

optional arguments:
  -h, --help            show this help message and exit
  -i AWS_ID, --id AWS_ID
                        AWS account ID for consolidated billing. Required
                        unless using the --local argument.
  -b S3_BILLING_BUCKET, --bucket S3_BILLING_BUCKET
                        S3 billing bucket name. Required unless using the
                        --local argument.
  -L LOCAL_BILLING_CSV, --local LOCAL_BILLING_CSV
                        Read a consolidated billing CSV from the filesystem
                        and bypass downloading from S3.
  -s, --save            Save the billing CSV to the local directory.
  -q, --quiet           Do not print to STDOUT.
  -o, --ou              Use AWS Organizational Units to group users. This
                        option will greatly increase the amount of time it
                        takes the script to run. If this option is specified,
                        but no OUs have been defined for this consolidated
                        billing group, the script will still run successfully
                        but will take much longer to complete.
  -l LIMIT, --limit LIMIT
                        Do not display spends less than this value in USD on
                        the report. Any spends not displayed will still be
                        counted towards all totals. Default is $5.00USD.
  -D, --display_ids     Display AWS account IDs in the report.
  -f, --full            Generate a full report. This option is only useful
                        when using OUs in a consolidated billing setting, and
                        the --ou option is used. An additional section is
                        added at the end of the original report that lists all
                        users sorted by spend. If the --ou argument is not
                        set, this option will be ignored.
  -e, --email           Send the report as an email, using the settings
                        defined in emailsettings.py.
  -w, --weekly          Formats the email subject and body to deonte a
                        "weekly" report on spend, from the start of the
                        current month to the present day.
  -m, --monthly         Formats the email subject and body to denote an "end
                        of month" report.

Please refer to README.md for more detailed usage instructions and examples.
```

## Contributing/Support

Please feel free to open issues and pull requests, and we will get to them in
a reasonable amount of time!
