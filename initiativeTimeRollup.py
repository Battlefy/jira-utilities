import argparse
import epicTimeRollup
from dataclasses import dataclass, asdict
import os
import sys
import datetime
import math
import calendar
import shutil
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from jira import JIRA
from subprocess import Popen


### Constants ###

INITIAL_TIME_KEY = "customfield_11609"
REMAINING_TIME_KEY = "customfield_11639"
CONFIDENCE_INTERVAL_KEY = "customfield_11641"
INCOMPLETE_ISSUE_COUNT_KEY = "customfield_11642"
START_DATE_KEY = "customfield_11600"


### Data Structures ###

@dataclass
class EpicIntervalCommitment:
    initiativeSummary: str
    epicSummary: str
    time: float

    def dict(self):
        return {'initiative_summary': self.initiativeSummary, 'epic_summary': self.epicSummary, 'proportional_time_commitment': self.time}


@dataclass
class MonthWorkload:
    month: int
    epics: []
    summed_time: []
    remaining_time: []

    def dict(self):
        epics_json = []
        for epic in self.epics:
            epics_json.append(epic.dict())

        summed_time_json = []
        summed_time_summary = 0.0
        for summed_time_local in self.summed_time:
            summed_time_json.append(summed_time_local.dict())
            summed_time_summary += summed_time_local.time

        remaining_time_json = []
        remaining_time_summary = 0.0
        for remaining_time_local in self.remaining_time:
            remaining_time_json.append(remaining_time_local.dict())
            remaining_time_summary += remaining_time_local.time

        return {'summed_time_summary': summed_time_summary, 'remaining_time_summary': remaining_time_summary, 'summed_time': summed_time_json, 'remaining_time': remaining_time_json, 'epics': epics_json}


@dataclass
class Initiative:
    initiative: JIRA.issue
    epics: []
    summed_time: float
    remaining_time: float
    incomplete_estimated_count: int
    incomplete_unestimated_count: int
    estimation_confidence: float
    story_point_weight: float
    story_point_weight_ceiling: float

    def calculate_estimate_counts(self):
        """
            Used to recalculate all the calculated member variables of the class.
        """
        self.summed_time = 0
        self.remaining_time = 0
        self.incomplete_unestimated_count = 0
        self.incomplete_estimated_count = 0

        for epic in self.epics:
            self.summed_time += epic.summed_time
            self.remaining_time += epic.remaining_time
            self.incomplete_estimated_count += epic.incomplete_estimated_count
            self.incomplete_unestimated_count += epic.incomplete_unestimated_count

        print("Debug: calculate estimate for {}, {}".format(self.initiative.key, self.summed_time))

        self.estimation_confidence = 0 if self.incomplete_estimated_count == 0 and self.incomplete_unestimated_count == 0 else (
            self.incomplete_estimated_count / (self.incomplete_estimated_count + self.incomplete_unestimated_count))
        self.estimation_confidence = self.estimation_confidence * 100

        story_point_average = 0 if self.incomplete_estimated_count == 0 else self.remaining_time / \
            self.incomplete_estimated_count

        if self.estimation_confidence != 0:
            # weight in the distribution of story points
            # if the average story points per ticket is <=story_point_weight (default 5)
            # retain our weighting; if not, reduce confidence rating
            # by at most story_point_weight_ceiling (default 80%)
            if story_point_average < self.story_point_weight:
                story_point_average = self.story_point_weight
            elif story_point_average > self.story_point_weight_ceiling:
                story_point_average = self.story_point_weight_ceiling

            self.estimation_confidence *= (self.story_point_weight /
                                           story_point_average)

        if self.estimation_confidence > 95:
            self.estimation_confidence = 95

        self.estimation_confidence = round(self.estimation_confidence, 2)

    def dict(self):
        self.calculate_estimate_counts()

        epic_json = []
        for epic in self.epics:
            epic_json.append(epic.dict())

        return {'key': self.initiative.key, 'summary': self.initiative.fields.summary, 'summed_time': self.summed_time, 'remaining_time': self.remaining_time, 'incomplete_estimated_count': self.incomplete_estimated_count, 'incomplete_unestimated_count': self.incomplete_unestimated_count, 'estimation_confidence': self.estimation_confidence, 'epics': epic_json}

### Methods ###


def diff_month(d1, d2):
    """
        Calendar utility method to get the number months between two dates.
        d1 - the first date to use.
        d2 - the second date to use.
    """
    return (d1.year - d2.year) * 12 + d1.month - d2.month


def get_next_month_start_date(start_date, month_to_add):
    """
        Calendar utility method to get the next month start date given an initial date, and months to add.
        start_date - The date to start calculations from.
        month_to_add - The number of months to add to the start date.
    """
    year = start_date.year
    month = start_date.month
    day = 1

    while month_to_add > 0:
        if month + 1 <= 12:
            month += 1
        else:
            year += 1
            month = 1
        month_to_add -= 1

    return datetime.datetime(year, month, day)


def get_current_month_end_date(current_date, end_bound_date):
    """
        Calendar utility to get the end date of the current month.
        current_date - The current date from which we work from.
        end_bound_date - The end date we want to clamp against.
    """
    if current_date.month == end_bound_date.month and end_bound_date.year == current_date.year:
        return end_bound_date
    else:
        return datetime.datetime(current_date.year, current_date.month, calendar.monthrange(current_date.year, current_date.month)[1])


def export_capacity_calendar(root, month_distributions):
    """
        Used to generate a capacity calendar.
        root - the root folder in which to place the output file.
        month_distributions - List of data structures which contain the capacity roll-up.
    """
    months_json = {}
    for month_key in month_distributions:
        months_json[month_key] = month_distributions[month_key].dict()

    out_file_path = os.path.join(
        root, "Calendar_estimates.json")

    with open(out_file_path, "w") as output_file:
        print("Writing file {}".format(out_file_path))
        output_file.writelines(json.dumps(
            months_json, indent=4, separators=(",", ": ")))

    print("Finished writing to file.")


def export_initiatives_json(root, initiatives_container):
    """
        Exports initiatives to json.
        root - fully qualified path to folder in which to write to.
        initiatives_container - the list of initiative DataObjects to export as JSON.
    """
    initaitives_json = {}
    for initiative_container in initiatives_container:
        if initiative_container.initiative.fields.project.key not in initaitives_json:
            initaitives_json[initiative_container.initiative.fields.project.key] = [
            ]

        print("Processing to JSON structure of {}".format(
            initiative_container.initiative.key))

        initaitives_json[initiative_container.initiative.fields.project.key].append(
            initiative_container.dict())

    for project_key in initaitives_json:
        out_file_path = os.path.join(
            root, "{}_estimates.json".format(project_key))

        with open(out_file_path, "w") as output_file:
            print("Writing file {}".format(out_file_path))
            output_file.writelines(json.dumps(
                initaitives_json[project_key], indent=4, separators=(",", ": ")))

    print("Finished writing to file.")


def parse_args(args_list):
    """
    Parse arguments for epic-time-rollup.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--api_token", required=True)
    parser.add_argument("--auto_initiatives", action='store_true')
    parser.add_argument("--initiatives")
    parser.add_argument("--update_ticket_estimates", action='store_true')
    parser.add_argument("--force_toplevel_recalculate", action='store_true')
    parser.add_argument("--export_estimates", action='store_true')
    parser.add_argument("--export_estimates_path")
    parser.add_argument("--export_project_configs", action='store_true')
    parser.add_argument("--export_project_config_path")
    parser.add_argument("--import_project_configs", action='store_true')
    parser.add_argument("--import_project_configs_path")
    parser.add_argument("--story_point_weight", default=5)
    parser.add_argument("--story_point_weight_ceiling", default=25)
    parser.add_argument("--update_sheets", action='store_true')
    parser.add_argument("--sheets_service_auth_file")
    parser.add_argument("--update_initiative_estimates", action='store_true')
    parser.add_argument("--create_calendar_schedule", action='store_true')

    args = parser.parse_args(args=args_list)

    # If we do not provide auto_initiatives, we must provide a list of specific initiatives to exercise.
    if args.auto_initiatives == False:
        if args.initiatives is None:
            argparse.ArgumentError(
                "User did not provided --auto_initiatives option but also did not provide --initiatives")
            sys.exit(-3)
    else:
        args.initiatives = None

    if args.update_sheets == True:
        if args.sheets_service_auth_file is None:
            argparse.ArgumentError(
                "User provided --update_sheets option but did not provide --sheets_service_auth_file")
            sys.exit(-4)

    return args


def create_epic_rollup_args(source_args, initiative, epics):
    """
        Creates arguments for epic script given source_args, the initaitive to execute it on, and list of epics.
        source_args - arguments to use as passthrough
        initiative - the initiative we are running the epic roll-up for
        epics - the list of epics to calculate the rollup for.
    """
    epic_rollup_args = source_args.copy()
    idx = -1

    if "--initiatives" in epic_rollup_args:
        idx = epic_rollup_args.index('--initiatives')
    elif "--auto_initiatives" in epic_rollup_args:
        idx = epic_rollup_args.index('--auto_initiatives')

    if(idx > -1):
        del epic_rollup_args[idx]
        del epic_rollup_args[idx]
        epic_rollup_args.append('--epics')
        epic_rollup_args.append(','.join(epics))

    idx = epic_rollup_args.index("--export_estimates_path")

    if idx > -1:
        idx = idx+1
        epic_rollup_args[idx] = os.path.join(epic_rollup_args[idx], initiative)
        if os.path.exists(epic_rollup_args[idx]):
            shutil.rmtree(epic_rollup_args[idx])
        os.mkdir(epic_rollup_args[idx])

    return epic_rollup_args


def calculate_initial_estimation(initiative_issue, initial_time_key, story_point_weight, story_point_weight_ceiling):
    """
        Calculate the estimation for an initiative in 'Initial Estimation' status. This will ignore all roll-up, and take the Story Point Estimate from the 
        initiative. 
        initiative_issue - JIRA issue in which to calculate the estimate for.
        initial_time_key - Custom Field Key for initial estimation.
        story_point_weight - Weighted value to be used in calculating the confidence interval.
        story_point_weight_ceiling - The max value to use for weighted story point calculations.
    """
    estimate = getattr(initiative_issue.fields, initial_time_key)
    epic = epicTimeRollup.Epic(
        initiative_issue, [], estimate, estimate, 1, 1)
    curr_initiative = Initiative(
        initiative_issue, [epic], 0.0, 0.0, 0, 0, 0.0, story_point_weight, story_point_weight_ceiling)

    curr_initiative.remaining_time = estimate
    curr_initiative.summed_time = estimate
    return curr_initiative


def calculate_estimation(args_list, filtered_keys, initiative_issue, story_point_weight, story_point_weight_ceiling):
    """
        Calculate the estimation for an initiative in 'Active Estimation', 'In Progress' status. This will calculate the complete roll-up for the epics.
        args_list - Passthrough args to be sent to the epic rollup.
        filtered_keys - The list of epics to perform a rollup against.
        initiative_issue - JIRA issue in which to calculate the estimate for.
        story_point_weight - Weighted value to be used in calculating the confidence interval.
        story_point_weight_ceiling - The max value to use for weighted story point calculations.
    """
    new_args = create_epic_rollup_args(
        args_list, initiative_issue.key, filtered_keys)
    epics_container = epicTimeRollup.execute(
        new_args) if len(filtered_keys) != 0 else []

    curr_initiative = Initiative(
        initiative_issue, epics_container, 0.0, 0.0, 0, 0, 0.0, story_point_weight, story_point_weight_ceiling)

    curr_initiative.calculate_estimate_counts()
    return curr_initiative


### Main ###

def execute(args_list):
    args = parse_args(args_list)

    print("Running JIRA Tabulations for Initiatives")
    jira_options = {"server": "https://battlefy.atlassian.net"}
    jira = JIRA(
        options=jira_options,
        basic_auth=(args.user, args.api_token),
    )

    if args.initiatives is not None:
        initiatives = args.initiatives.split(",")
    elif args.auto_initiatives:
        # FRONT-15 is the ops epic.
        query_string = "project=FRONT and type=Epic and id!=Front-15"
        initiatives = list(
            set([e.key for e in jira.search_issues(query_string)]))

    initiatives_container = []

    for initiative in initiatives:
        print("Obtaining roll-up for {}".format(initiative))
        initiative_issue = jira.issue(initiative)

        keys = [
            x.inwardIssue.key for x in initiative_issue.fields.issuelinks if hasattr(x, 'inwardIssue') and 'FRONT' not in x.inwardIssue.key and 'SALES' not in x.inwardIssue.key]
        filtered_keys = []
        curr_initiative = None

        if initiative_issue.fields.status.name == 'Done':
            continue

        if initiative_issue.fields.status.name == 'Initial Estimation':
            curr_initiative = calculate_initial_estimation(
                initiative_issue, INITIAL_TIME_KEY, args.story_point_weight, args.story_point_weight_ceiling)
        else:
            filtered_keys.extend(keys)
            curr_initiative = calculate_estimation(
                args_list, filtered_keys, initiative_issue, args.story_point_weight, args.story_point_weight_ceiling)

        initiatives_container.append(curr_initiative)

    if args.update_initiative_estimates:
        # update the SP estimate on the initiatives
        for initiative in initiatives_container:
            print("Updating initiative: {}".format(initiative.initiative.key))

            initiative.initiative.update(fields={
                INITIAL_TIME_KEY: initiative.summed_time})
            initiative.initiative.update(fields={
                REMAINING_TIME_KEY: initiative.remaining_time})
            initiative.initiative.update(fields={
                CONFIDENCE_INTERVAL_KEY: int(initiative.estimation_confidence)})
            initiative.initiative.update(fields={
                                         INCOMPLETE_ISSUE_COUNT_KEY: initiative.incomplete_estimated_count+initiative.incomplete_unestimated_count})

    if args.export_estimates:
        export_initiatives_json(
            args.export_estimates_path, initiatives_container)

    month_distributions = {}

    if args.create_calendar_schedule:
        skipped_epics = []
        print("Calculating calendar rooted capacity demand...")
        for initiative in initiatives_container:
            for epic in initiative.epics:
                initiative_start_date_object = None
                initiative_end_date_object = None
                start_date_object = None
                end_date_object = None

                # Confirm we have an initiative start date; if we don't have that all bets are off anyways
                # check start date of epic; if we don't have that, we yield to the start date of the initiative
                # if we do have it, we still need to sanity check that the epic doesn't start before the initiatve; if so assume the start date is the
                # initiative.
                # If we don't have that, we set the start date to the same month as the end_date
                if getattr(initiative.initiative.fields, START_DATE_KEY) is None:
                    skipped_epics.append(epic)
                    continue
                else:
                    initiative_start_date_object = datetime.datetime.strptime(
                        getattr(initiative.initiative.fields, START_DATE_KEY), "%Y-%m-%d")

                if getattr(epic.epic.fields, START_DATE_KEY) is not None:
                    start_date_object = datetime.datetime.strptime(
                        getattr(epic.epic.fields, START_DATE_KEY), "%Y-%m-%d")
                    if start_date_object < initiative_start_date_object:
                        start_date_object = initiative_start_date_object

                if epic.epic.fields.duedate is not None:
                    end_date_object = datetime.datetime.strptime(
                        epic.epic.fields.duedate, "%Y-%m-%d")
                elif initiative.initiative.fields.duedate is not None:
                    end_date_object = datetime.datetime.strptime(
                        initiative.initiative.fields.duedate, "%Y-%m-%d")
                else:
                    skipped_epics.append(epic)
                    continue
                # TODO - but... whyyyyyyyy ;-;
                if getattr(epic.epic.fields, START_DATE_KEY) is None:
                    start_date_object = datetime.datetime(
                        end_date_object.year, end_date_object.month, end_date_object.day)

                total_delta_days = (
                    end_date_object - start_date_object).days + 1

                summed_calc_total_delta_days = (end_date_object - datetime.datetime.today()).days + 1 if start_date_object < datetime.datetime.today(
                ) and datetime.datetime.today() < end_date_object else total_delta_days
                delta_months = diff_month(end_date_object, start_date_object)+1

                itr_date = start_date_object

                for i in range(delta_months):
                    end_date = get_current_month_end_date(
                        itr_date, end_date_object)
                    micro_delta_days = (end_date - itr_date).days + 1
                    month_distribution_key = str(
                        itr_date.year)+"-"+str(itr_date.month)
                    if month_distribution_key not in month_distributions:
                        month_distributions[month_distribution_key] = MonthWorkload(
                            itr_date.month, [], [], [])
                    month_distributions[month_distribution_key].epics.append(
                        epic)

                    month_distributions[month_distribution_key].summed_time.append(EpicIntervalCommitment(initiative.initiative.fields.summary, epic.epic.fields.summary, round(float(
                        epic.summed_time * (micro_delta_days / total_delta_days)), 2)))

                    # remaining time is only pertinent for the section of time after today()
                    if (itr_date < datetime.datetime.today()):
                        # adjust for the case where we are currently calculating this month, wherein we want to provide some partial
                        # counting; if end_date < today, we are over and all work must be done.
                        if (itr_date.month == datetime.datetime.today().month) and (itr_date.year == datetime.datetime.today().year):
                            micro_delta_days = (
                                end_date - datetime.datetime.today()).days + 1 if (end_date_object - datetime.datetime.today()).days > 0 else summed_calc_total_delta_days
                        else:
                            micro_delta_days = 0
                            # if this is the last loop, and the nested epic is over, we need to just frontload the entire remaining work into next month

                    month_distributions[month_distribution_key].remaining_time.append(EpicIntervalCommitment(initiative.initiative.fields.summary, epic.epic.fields.summary, round(float(
                        epic.remaining_time * (micro_delta_days / summed_calc_total_delta_days)), 2)))
                    itr_date = get_next_month_start_date(itr_date, 1)

        # serialize calendar plan
        export_capacity_calendar(
            args.export_estimates_path, month_distributions)
        print("Calendar render complete.")

    if args.update_sheets:
        print("Updating the google sheet...")
        scope = ['https://spreadsheets.google.com/feeds',
                 'https://www.googleapis.com/auth/drive']
        credentials = ServiceAccountCredentials.from_json_keyfile_name(
            args.sheets_service_auth_file, scope)
        gc = gspread.authorize(credentials)
        spreadsheet_instance = gc.open_by_url(
            "https://docs.google.com/spreadsheets/d/1NvyO1Wj-cCMEGwHpPkFgGl14Kdpmz2QR8NDNx18FBAo/edit?usp=sharing")
        alloc = spreadsheet_instance.sheet1
        root_cell_row = 50
        root_cell_col = 'H'

        years = [2020, 2021]
        months = list(range(1, 13))
        counter = 0

        for year in years:
            for month in months:
                new_row = root_cell_row + counter
                new_cell = '{}{}'.format(root_cell_col, new_row)
                month_distribution_key = '{}-{}'.format(year, month)

                if month_distribution_key in month_distributions:
                    ret_dict = month_distributions[month_distribution_key].dict(
                    )
                    alloc.update_acell(
                        new_cell, ret_dict['remaining_time_summary'])

                counter += 1
        alloc.update_acell('G49', 'Updated On: {}'.format(
            datetime.datetime.today()))
