from jira import JIRA
from dataclasses import dataclass, asdict
import argparse
import json
import sys
import os

### Constants ###

EPIC_NAME = "Epic"
STORY_NAME = "Story"
TASK_NAME = "Task"
SUBTASK_NAME = "Subtask"
BUG_NAME = "Bug"

issue_types = None
project_strtype_id_map = None

### Data Structures ###
@dataclass
class UserStory:
    issue: JIRA.issue
    subtasks: []
    summed_time: float

    def dict(self):
        return {'key': self.issue.key, 'summary': self.issue.fields.summary, 'status': self.issue.fields.status.name, 'time': self.summed_time}


@dataclass
class Epic:
    epic: JIRA.issue
    issues: []
    summed_time: float
    remaining_time: float
    incomplete_estimated_count: int
    incomplete_unestimated_count: int

    def add_issues(self, jira, project_configs, update_ticket_estimates, force_toplevel_recalculate, new_issues):
        """
        """
        for issue in new_issues:
            print("Debug: epic {} has issue {}".format(self.epic.key, issue.issue.key))
            extract_issue_estimate(
                jira, issue, project_configs[self.epic.fields.project.id], update_ticket_estimates, force_toplevel_recalculate)

            self.summed_time += issue.summed_time
            if issue.issue.fields.status.name != "Done":
                self.remaining_time += issue.summed_time
                if issue.summed_time <= 0.0:
                    self.incomplete_unestimated_count += 1
                else:
                    self.incomplete_estimated_count += 1
        self.issues.extend(new_issues)

    def dict(self):
        issues_json = []

        for issue in self.issues:
            di = issue.dict()
            issues_json.append(issue.dict())

        return {'key': self.epic.key, 'summary': self.epic.fields.summary, 'time': self.summed_time, 'remaining_time': self.remaining_time, 'subticket_count': len(self.issues), 'incomplete_estimated_count': self.incomplete_estimated_count, 'incomplete_unestimated_count': self.incomplete_unestimated_count, 'issues': issues_json}


@dataclass
class IssueBundle:
    type_id: int
    estimation_key: str

    def dict(self):
        return {'type_id': self.type_id, "estimation_key": self.estimation_key}


@dataclass
class ProjectConstants:
    key = str
    epic = IssueBundle
    story = IssueBundle
    subtask = IssueBundle
    task = IssueBundle
    bug = IssueBundle

    def dict(self):
        return {'key': self.key, EPIC_NAME: self.epic.dict(), STORY_NAME: self.story.dict(), TASK_NAME: self.task.dict(), SUBTASK_NAME: self.subtask.dict(), BUG_NAME: self.bug.dict()}

### Methods ###

def parse_args(args_list):
    """
    Parse arguments for epic-time-rollup.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    parser.add_argument("--api_token", required=True)
    parser.add_argument("--epics", required=True)
    parser.add_argument("--update_ticket_estimates", action='store_true')
    parser.add_argument("--force_toplevel_recalculate", action='store_true')
    parser.add_argument("--export_estimates", action='store_true')
    parser.add_argument("--export_estimates_path")
    parser.add_argument("--export_project_configs", action='store_true')
    parser.add_argument("--export_project_config_path")
    parser.add_argument("--import_project_configs", action='store_true')
    parser.add_argument("--import_project_configs_path")

    args, passthrough = parser.parse_known_args(args=args_list)

    if(args.export_estimates == True):
        if args.export_estimates_path is None:
            argparse.ArgumentError(
                "User provided --export_estimates, but no value for --export_estimates_path .")
            sys.exit(-2)

    if(args.export_project_configs == True):
        if args.export_project_config_path is None:
            argparse.ArgumentError(
                "User provided --export_project_configs, but no value for --export_project_config_path .")
            sys.exit(-2)

    if(args.import_project_configs == True):
        if args.import_project_configs_path is None:
            argparse.ArgumentError(
                "User provided --import_project_configs, but no value for --import_project_configs_path .")
            sys.exit(-2)

    return args


def generate_project_constants(jira, project, load_from_file=False, configuration_folder_root=None):
    """
        Generates a data struct that represents all of the const strings used for important jira Keys. The reasoning for doing this is between projects, there may be 
        different custom field keys for any required fields (in our case, estimates).
        jira - the jira connection.
        project - the jira project.
        configuration_folder_root - fully qualified path of initialization file to use.
    """
    global project_strtype_id_map

    project_id = project.id
    full_project = jira.project(project.id)

    if load_from_file == True:
        import_path = os.path.join(configuration_folder_root,
                                   "{}_config.json".format(full_project.key))
        if os.path.exists(import_path):
            with open(import_path, 'r') as read_file:
                file_content = read_file.read()

                project_constants_json = json.loads(file_content)
                project_constants = ProjectConstants()
                project_constants.key = project_constants_json['key']
                project_constants.epic = IssueBundle(
                    project_constants_json[EPIC_NAME]['type_id'], project_constants_json[EPIC_NAME]['estimation_key'])

                project_constants.story = IssueBundle(
                    project_constants_json[STORY_NAME]['type_id'], project_constants_json[STORY_NAME]['estimation_key'])

                project_constants.task = IssueBundle(
                    project_constants_json[TASK_NAME]['type_id'], project_constants_json[TASK_NAME]['estimation_key'])

                project_constants.subtask = IssueBundle(
                    project_constants_json[SUBTASK_NAME]['type_id'], project_constants_json[SUBTASK_NAME]['estimation_key'])

                project_constants.bug = IssueBundle(
                    project_constants_json[BUG_NAME]['type_id'], project_constants_json[BUG_NAME]['estimation_key'])

                return project_constants

    # Dynamically create project infomation by naming convention
    if project_strtype_id_map is None:
        project_strtype_id_map = {}

    if project.id not in project_strtype_id_map:
        project_strtype_id_map[project.id] = {}
        for issue_type in full_project.issueTypes:
            project_strtype_id_map[project.id][issue_type.name] = {
                "id": issue_type.id}

            # process custom field associated with 'Story point estimate'
            meta = jira.createmeta(projectKeys=str(project.key), issuetypeIds=str(
                issue_type.id), expand="projects.issuetypes.fields")

            try:
                issue_expanded_data = meta['projects'][0]['issuetypes'][0]
                for field_key in issue_expanded_data['fields']:
                    if issue_expanded_data['fields'][field_key]['name'] == 'Story point estimate':
                        project_strtype_id_map[project.id][issue_type.name]['estimate_field'] = field_key
            except Exception as e:
                print("Failed to extract metadata needed for estimates for project {} for issue data {}".format(project.key, issue_expanded_data))
                print(e)
                sys.exit(-1)

    try:
        # test for existence of issue types.
        projectConstants = ProjectConstants()
        projectConstants.key = full_project.key

        if project_strtype_id_map.get(project_id).get(SUBTASK_NAME) is not None:
            projectConstants.subtask = IssueBundle(
                project_strtype_id_map.get(project_id).get(SUBTASK_NAME).get("id"), project_strtype_id_map.get(project_id).get(SUBTASK_NAME).get('estimate_field'))

        if project_strtype_id_map.get(project_id).get(TASK_NAME) is not None:
            projectConstants.task = IssueBundle(
                project_strtype_id_map.get(project_id).get(TASK_NAME).get("id"), project_strtype_id_map.get(project_id).get(TASK_NAME).get('estimate_field'))

        if project_strtype_id_map.get(project_id).get(STORY_NAME) is not None:
            projectConstants.story = IssueBundle(
                project_strtype_id_map.get(project_id).get(STORY_NAME).get("id"), project_strtype_id_map.get(project_id).get(STORY_NAME).get('estimate_field'))

        if project_strtype_id_map.get(project_id).get(EPIC_NAME) is not None:
            projectConstants.epic = IssueBundle(project_strtype_id_map.get(
                project_id).get(EPIC_NAME).get("id"), project_strtype_id_map.get(project_id).get(EPIC_NAME).get('estimate_field'))

        if project_strtype_id_map.get(project_id).get(BUG_NAME) is not None:
            projectConstants.bug = IssueBundle(
                project_strtype_id_map.get(project_id).get(BUG_NAME).get("id"), project_strtype_id_map.get(project_id).get(BUG_NAME).get('estimate_field'))

    except Exception as e:
        print("Issue creating projectConstants struct for {}".format(project.key))
        print(e)

    return projectConstants


def extract_issue_estimate(jira, epic_sub_issue, project_constants, update_ticket_estimates=False, force_toplevel_recalculate=False):
    """
        Extracts the issue estimate.
        jira - the jira connection.
        epic_sub_issue - the jira item to estimate.
        project_constants - project constants used to determine task type & customs.
    """
    print("Extracting time for issue: {}".format(epic_sub_issue.issue.key))

    unestimated_subtasks = []

    # If it's a task, there is no further roll-up
    if epic_sub_issue.issue.fields.issuetype.id == project_constants.task.type_id:
        print("Debug: task {}, has an estimate of {}".format(epic_sub_issue.issue.key, getattr(epic_sub_issue.issue.fields, project_constants.task.estimation_key)))
        if hasattr(epic_sub_issue.issue.fields, project_constants.task.estimation_key) and getattr(epic_sub_issue.issue.fields, project_constants.task.estimation_key) is not None:
            epic_sub_issue.summed_time += float(
                getattr(epic_sub_issue.issue.fields, project_constants.task.estimation_key))
    # If it's a story, we have two cases:
    # 1) There is already a roll-up/estimate at the user-story level
    # 2) There is no roll-up/estimate at the user-story level
    elif epic_sub_issue.issue.fields.issuetype.id == project_constants.story.type_id:
        if (force_toplevel_recalculate and len(epic_sub_issue.subtasks) > 0) or getattr(epic_sub_issue.issue.fields, project_constants.story.estimation_key) is None:
            for subtask in epic_sub_issue.subtasks:
                fetched = jira.issue(
                    subtask.key,
                    fields="{}, subtasks, issuetype".format(
                        project_constants.story.estimation_key),
                )

                if (
                    hasattr(fetched.fields,
                            project_constants.story.estimation_key)
                    and getattr(fetched.fields, project_constants.story.estimation_key) is not None
                ):
                    epic_sub_issue.summed_time += float(
                        getattr(fetched.fields, project_constants.story.estimation_key))
                else:
                    unestimated_subtasks.append(fetched.key)

            if update_ticket_estimates:
                # We want to make sure that we aren't flattening 'user story level estimates' with sub-task roll-up if that is not
                # how teams are estimating. So if summed_time is 0.0, just yield to what's there already.
                val = getattr(epic_sub_issue.issue.fields,
                              project_constants.story.estimation_key)
                              #TODO - inspect whether this should be remaining
                max_value = val if epic_sub_issue.summed_time == 0 else epic_sub_issue.summed_time
                epic_sub_issue.summed_time = max_value if max_value is not None else 0.0
                epic_sub_issue.issue.update(
                    fields={project_constants.story.estimation_key: max_value})
        else:
            epic_sub_issue.summed_time += float(
                getattr(epic_sub_issue.issue.fields, project_constants.story.estimation_key))


def update_ticket_estimates(epic_containers, project_configs):
    """
        Updates the actual jira issues to reflect the new estimates.
        epic_containers - list of epics which we want to update the toplevel estimates.
        project_configs - dictionary of jira project configurations used to update the jira estimates.
    """
    for epic_container in epic_containers:
        project_constants = project_configs[epic_container.epic.fields.project.id]
        val = getattr(epic_container.epic.fields,
                      project_constants.epic.estimation_key)
        max_value = val if epic_container.summed_time == 0 or epic_container.summed_time == 0.0 else epic_container.summed_time
        epic_container.epic.update(
            fields={project_constants.epic.estimation_key: max_value})


def export_epics_json(root, epics_container):
    """
        Exports the epics to json.
        root - fully qualified path to folder in which to write to.
        epics_container - the list of epic DataObjects to export as JSON.
    """
    projects_json = {}
    for epic_container in epics_container:
        if epic_container.epic.fields.project.key not in projects_json:
            projects_json[epic_container.epic.fields.project.key] = []

        print("Processing to JSON structure of {}".format(epic_container.epic.key))

        projects_json[epic_container.epic.fields.project.key].append(
            epic_container.dict())

    for project_key in projects_json:
        out_file_path = os.path.join(
            root, "{}_estimates.json".format(project_key))

        with open(out_file_path, "w") as output_file:
            output_file.writelines(json.dumps(
                projects_json[project_key], indent=4, separators=(",", ": ")))

    print("Finished writing to file.")


def export_project_configs_json(root, project_configs_container):
    """
        Exports the project configs to JSON for later reuse.
        root - Root folder in which to export the project configs to.
        project_configs_container - The list of project configs.
    """
    for project in project_configs_container:
        out_file_path = os.path.join(
            root, "{}_config.json".format(project_configs_container[project].key))

        with open(out_file_path, "w") as output_file:
            dictthing = project_configs_container[project].dict()
            output_file.writelines(json.dumps(
                project_configs_container[project].dict(), indent=4, separators=(",", ": ")))

### Main ###

def execute(args_list):
    args = parse_args(args_list)
    print("Running JIRA Tabulations for Epics")
    jira_options = {"server": "https://battlefy.atlassian.net"}
    jira = JIRA(
        options=jira_options,
        basic_auth=(args.user, args.api_token),
    )
    epics = args.epics.split(",")

    epics_container = []
    project_configs = {}

    for epic in epics:
        try:
            issue = jira.issue(epic)

            if issue.fields.project.key not in project_configs:
                project_configs[issue.fields.project.id] = generate_project_constants(
                    jira, issue.fields.project, load_from_file=args.import_project_configs, configuration_folder_root=args.import_project_configs_path)

            epic_container = Epic(issue, [], 0.0, 0.0, 0.0, 0.0)
            epics_container.append(epic_container)

        except Exception as e:
            print("Unable to access epic {}".format(epic))
            print(e)

    for epic_container in epics_container:
        try:
            query_string = "parent={}".format(epic_container.epic.key)
            cust_keys = list(set([project_configs[epic_container.epic.fields.project.id].story.estimation_key,
                                  project_configs[epic_container.epic.fields.project.id].task.estimation_key]))
            cust_key_str = ",".join(cust_keys)

            epic_issues = [
                UserStory(
                    e, e.fields.subtasks if hasattr(
                        e.fields, "subtasks") else [], 0.0
                )
                for e in jira.search_issues(
                    query_string,
                    maxResults=1000,
                    fields="{}, subtasks, status, summary, issuetype".format(
                        cust_key_str
                    )
                )
            ]
            epic_container.add_issues(
                jira, project_configs, args.update_ticket_estimates, args.force_toplevel_recalculate, epic_issues)

        except Exception as e:
            print("Issue extracting child objects.")

    if args.update_ticket_estimates:
        update_ticket_estimates(epics_container, project_configs)

    if args.export_estimates:
        export_epics_json(args.export_estimates_path, epics_container)

    if args.export_project_configs:
        export_project_configs_json(
            args.export_project_config_path, project_configs)

    return epics_container
