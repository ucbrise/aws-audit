# aws-audit.py

a script that will download an AWS consolidated bill, and parse out spending

## install
you need to have python 2.7 and the latest version of boto3 installed via your package manager of choice.

## setup
make sure your aws credentials are in a location that boto3 can discover.  currently, the script will look for shared credentials in $HOME/.aws/credentials.  more details on how to configure this are here:  https://boto3.readthedocs.io/en/latest/guide/configuration.html#configuring-credentials

if you want to send email reports, please edit emailsettings.py and change the variables located there.

## usage
grab the most recent bill from S3, save a copy locally, and display the report to STDOUT using OUs and showing account IDs:
aws-audit.py -i <AWS_ID> -b <BILLING_BUCKET> --save --ou --display_ids

create a report on a downloaded billing CSV, not using OUs:
aws-audit.py --local <LOCAL_BILLING_CSV>

grab the most recent bill from S3 and email a report with OUs using the monthly template:
aws-audit.py -i <AWS_ID> -b <BILLING_BUCKET> --ou --email --monthly
