import matplotlib
matplotlib.use('Agg')
import pandas as pd
import matplotlib.pyplot as plt
import re
import sys

def account_spend_plot(csvfile=None, outputfilename=None, outputfiletype="png"):
  """
  creates a plot for account-based spends

  args:
    csvfile:  full path to the CSV file
    outputfilename:  name (without extension) of the outputted plot
    outputfiletype:  what type of file to output (default is png)

  returns:
    outfile:  full path to the created plot
  """
  outfile = str()
  if outputfilename is None:
    print('Must specify a filename to save the plot to.')
    sys.exit(1)
  else:
    outfile = outputfilename + '.' + outputfiletype

  indv = pd.read_csv(csvfile)
  indv['spend'] = indv['spend'].str.replace(re.compile(",|\$"), "").astype(float)

  indv.groupby('person')['spend'].sum().sort_values(ascending=False).head(20).plot(kind='bar')
  plt.savefig(outfile, bbox_inches='tight')

  return outfile

def org_spend_plot(csvfile=None, outputfilename=None, outputfiletype="png"):
  """
  creates a plot for org-based spends

  args:
    csvfile:  full path to the CSV file
    outputfilename:  name (without extension) of the outputted plot
    outputfiletype:  what type of file to output (default is png)

  returns:
    outfile:  full path to the created plot
  """
  outfile = str()
  if outputfilename is None:
    print('Must specify a filename to save the plot to.')
    sys.exit(1)
  else:
    outfile = outputfilename + '.' + outputfiletype

  proj = pd.read_csv(csvfile)
  proj['spend'] = proj['spend'].str.replace(re.compile(",|\$"), "").astype(float)

  proj.groupby('project')['spend'].sum().sort_values(ascending=False).head(20).plot(kind='bar')
  plt.savefig(outfile, bbox_inches='tight')

  return outfile
