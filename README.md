# jira-utilities
Collection of jira utilities that can be used to gather various operational metrics.

## Getting Started
### System Dependencies
1) python 3
2) pip

### Initialize Execution Environment
`Executed from project root`

    1) pip install virtualenv
    2) virtualenv env
    3) env/bin/pip install -r requirements.txt

### Running the script
`Executed from project root`

    env/bin/python3 epic-time-rollup.py --user {user} --api_token {token} --epics {comma separated list} --output_path {fully qualified path to output json}
