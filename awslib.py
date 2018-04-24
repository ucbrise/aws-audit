import boto3
import config
import csv
import datetime

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
    f = open(billing_file_path, 'r')
    billing_data = f.read()
  else:
    today = datetime.date.today()
    month = today.strftime('%m')
    year = today.strftime('%Y')
    billing_filename =  aws_id + '-aws-billing-csv-' + \
                        year + '-' + month + '.csv'

    s3 = boto3.resource('s3')
    b = s3.Object(billing_bucket, billing_filename)
    billing_data = b.get()['Body'].read().decode('utf-8')

    if not billing_data:
      print("unable to find billing data (%s) in your bucket!" % \
            billing_filename)
      sys.exit(-1)

  if (save):
    f = open(billing_filename, 'w')
    f.write(billing_data)
    f.close

  return csv.reader(billing_data.split('\n'))

def get_root_ou_id(aws_id):
  """
  get the ID of the ROOT OU

  args:
    aws_id:  AWS account number

  returns:
    namedtuple (id, name) with ID number of the ROOT OU and 'ROOT'
  """
  client = boto3.client('organizations')
  ou_r = client.list_roots()

  return config.NodeInfo(id=ou_r['Roots'][0]['Id'], name='ROOT')

def get_ou_children(ou_id):
  """
  get the list of OU children for a given OU id

  args:
    ou_id:  ID number of the current OU

  returns:
    children:  list of NodeInfo namedtuples or NoneType if no children OUs are
               present
  """
  client = boto3.client('organizations')
  ou_r = client.list_organizational_units_for_parent(ParentId=ou_id)

  children = list()

  while True:
    for ou in ou_r['OrganizationalUnits']:
      children.append(config.NodeInfo(id=ou['Id'], name=ou['Name']))

    if 'NextToken' in ou_r:
      ou_r = client.list_organizational_units_for_parent(
        ParentId=ou_id, NextToken=ou_r['NextToken'])
    else:
      break

  return children or None

def get_accounts_for_ou(ou_id):
  """
  get the accounts attached to a given ou_id

  args:
    ou_id:  ID number of an OU

  returns:
    accounts:  list of namedtuples with AWS ID and full name
  """
  client = boto3.client('organizations')
  ou_r = client.list_accounts_for_parent(ParentId=ou_id)

  accounts = list()
  while True:
    for acct in ou_r['Accounts']:
      accounts.append(config.Account(id=acct['Id'], name=acct['Name']))

    if 'NextToken' in ou_r:
      ou_r = client.list_accounts_for_parent(ParentId=ou_id,
                                             NextToken=ou_r['NextToken'])
    else:
      break

  return accounts or None

def get_accounts_for_org():
  """
  get a list of all accounts in the AWS org

  returns:
    aws_accounts:  a list of AWS account IDs
  """
  aws_accounts = list()
  client = boto3.client('organizations')
  ou_r = client.list_accounts()

  while True:
    for acct in ou_r['Accounts']:
      aws_accounts.append(acct['Id'])

    if 'NextToken' in ou_r:
      ou_r = client.list_accounts(NextToken=ou_r['NextToken'])
    else:
      break

  return aws_accounts
