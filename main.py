import harvest
from yaml import load
from datetime import datetime, timedelta
# from jira_connection import jira
from jira import JIRA
from dateutil import parser
import re
import subprocess
import threading
import time
from typing import Dict

config_tokens = load(open('oauth_tokens.yml', 'r'))

# connection to harvest

h = harvest.Harvest('https://mev.harvestapp.com',
                    client_id='----',#FILL IT
                    token=config_tokens['access_token'],
                    token_updater=config_tokens['refresh_token'],
                    put_auth_in_header=False)

# connection to jira
options = {'server': 'https://center.atlassian.net'}
jira = JIRA(options=options, basic_auth=('login', 'pass'))


def sync_work_log(harvest_project_code, task_jira_mask):
    # Regex for find task in JIRA
    task_regx = re.compile(r'{0}\d+'.format(task_jira_mask))

    # Regex for find task id from harvest
    task_harvest_id_regx = re.compile(r'^\d+')

    # Set start and end day
    start = (datetime.today() - timedelta(days=14)).replace(hour=0, minute=0, second=0)
    end = datetime.today().replace(hour=0, minute=0, second=0) + timedelta(1)

    # get harvest projests
    projects = h.projects()
    for project in projects:
        if project['project']['code'] == harvest_project_code:
            # or project['project']['code'] == "NOVO.SOW29":

            # Get project
            project_id = project['project']['id']

            tasks = h.timesheets_for_project(project_id, start, end)

            for task in tasks:
                if 'day_entry' in task and 'notes' in task['day_entry'] and task['day_entry']['notes']:
                    ticket_match = re.search(task_regx, task['day_entry']['notes'])
                else:
                    ticket_match = None

                if ticket_match:
                    try:
                        issue = jira.issue(ticket_match.group())
                    except:
                        issue = None

                    if issue:
                        existing_worklog_ids = jira.worklogs(issue)
                        existing_worklogs = []
                        for worklog in existing_worklog_ids:
                            w = jira.worklog(issue, worklog)
                            harvest_task_id = re.search(task_harvest_id_regx, w.comment)
                            if harvest_task_id:
                                existing_worklogs.append(int(harvest_task_id.group()))

                        if task['day_entry']['id'] not in existing_worklogs:

                            time_spent_seconds = task['day_entry']['hours'] * 60 * 60
                            time_spent_seconds = int(time_spent_seconds)

                            started = task['day_entry']['created_at']
                            started = parser.parse(started)

                            harvest_user = h.get_person(task['day_entry']['user_id'])
                            user = '{0} {1}'.format(harvest_user['user']['first_name'],
                                                    harvest_user['user']['last_name'])

                            comment = '{0}: {1} - {2}'.format(task['day_entry']['id'], user, task['day_entry']['notes'])

                            task = h.get_task(task['day_entry']['task_id'])

                            if task['task']['name'] in ["Development", "Testing/QA", "Design (Visual)"] and time_spent_seconds > 0:
                                print(time_spent_seconds)
                                # if issue.fields.timetracking.remainingEstimateSeconds < time_spent_seconds:
                                #     issue.fields.timetracking.update(fields={"remainingEstimateSeconds": time_spent_seconds})
                                try:
                                    worklogs = jira.add_worklog(issue,
                                                                timeSpentSeconds=time_spent_seconds,
                                                                adjustEstimate='leave',
                                                                started=started,
                                                                comment=comment)

                                    print("Log new time")
                                except:
                                    print("Not log Log new time")
                            else:
                                print("not log it's not developnemt")
                            print((comment, issue.key))
                        else:
                            print(("Task with id {0}: exist {1}".format(task['day_entry']['id'],
                                                                        task['day_entry']['notes'])))


def calculate_days(estimate: int):
    m, s = divmod(estimate, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 6)
    return "%d days %d hours %02d minutes %02d sec" % (d, h, m, s)


def _get_issue_time(issue, versions_dict: Dict):
    if issue.fields.subtasks:
        for subtask in issue.fields.subtasks:
            subtask = jira.issue(subtask.id)
            # print (subtask.fields.aggregatetimeoriginalestimate)
            if subtask.fields.fixVersions:
                if subtask.fields.fixVersions[0].name in versions_dict and versions_dict[
                    subtask.fields.fixVersions[0].name]:
                    if subtask.fields.aggregatetimeestimate:
                        versions_dict[subtask.fields.fixVersions[0].name] \
                            = versions_dict[
                                            subtask.fields.fixVersions[
                                                0].name] + subtask.fields.aggregatetimeestimate
                else:
                    versions_dict[subtask.fields.fixVersions[0].name] = subtask.fields.aggregatetimeestimate
    else:
        if issue.fields.fixVersions:
            if issue.fields.fixVersions[0].name in versions_dict and versions_dict[
                issue.fields.fixVersions[0].name]:
                versions_dict[issue.fields.fixVersions[0].name] = \
                    versions_dict[issue.fields.fixVersions[0].name] + issue.fields.aggregatetimeestimate
            else:
                versions_dict[issue.fields.fixVersions[0].name] = issue.fields.aggregatetimeestimate


def _get_issue_time_epic(issue, dict_es: Dict):
    # if issue.fields.subtasks:
    #     for subtask in issue.fields.subtasks:
    #         subtask = jira.issue(subtask.id)
    #         # print (subtask.fields.aggregatetimeoriginalestimate)
    #         if subtask.fields.fixVersions:
    #             if subtask.fields.fixVersions[0].name in versions_dict and versions_dict[
    #                 subtask.fields.fixVersions[0].name]:
    #                 if subtask.fields.aggregatetimeestimate:
    #                     versions_dict[subtask.fields.fixVersions[0].name] = versions_dict[
    #                                                                             subtask.fields.fixVersions[
    #                                                                                 0].name] + subtask.fields.aggregatetimeestimate
    #             else:
    #                 versions_dict[subtask.fields.fixVersions[0].name] = subtask.fields.aggregatetimeestimate
    # else:
    if issue.fields.aggregatetimeestimate:
        if issue.fields.customfield_10008:
            if issue.fields.customfield_10008 in dict_es and dict_es[issue.fields.customfield_10008]:
                _get_issue_time(issue, dict_es[issue.fields.customfield_10008])
            else:
                dict_es[issue.fields.customfield_10008] = {}
                _get_issue_time(issue, dict_es[issue.fields.customfield_10008])
        elif "parent" in issue.raw["fields"] and issue.fields.parent:
            parent = jira.issue(issue.fields.parent.key)
            if parent.fields.customfield_10008 in dict_es and dict_es[parent.fields.customfield_10008]:
                _get_issue_time(issue, dict_es[parent.fields.customfield_10008])

            else:
                dict_es[parent.fields.customfield_10008] = {}
                _get_issue_time(issue, dict_es[parent.fields.customfield_10008])
        else:
            if "No Epic" in dict_es and dict_es["No Epic"]:
                _get_issue_time(issue, dict_es["No Epic"])

            else:
                dict_es["No Epic"] = {}
                _get_issue_time(issue, dict_es["No Epic"])
    else:
        print("Not estimated- {0}".format(issue.key))


def get_version_estimate():
    versions_dict = {}
    # boards = jira.boards()

    # sprints = jira.sprints(59)

    # jira.project()

    tasks = jira.incompleted_issues(59, 370)

    for task in tasks:
        _get_issue_time(task, versions_dict)

    time_data = []
    for key, value in versions_dict.items():
        time_data.append('{0} - {1}'.format(key, calculate_days(value)))

    return time_data


def get_estimates():
    versions_dict = {}
    dict_es = {}
    boards = jira.boards() #61

    sprints = jira.sprints(61) #375

    # jira.project()

    tasks = jira.incompleted_issues(61, 375)
    # tasks = jira.search_issues(
    #     "project = XB AND resolution = Unresolved ORDER BY priority DESC, updated DESC",
    #     maxResults=1000)

    threads = list()
    exceptions = list()
    sleep = 0
    for task in tasks:
        def _calculate(task, dict_es: Dict, versions_dict: Dict, sleep: float):
            time.sleep(sleep)
            try:
                issue = jira.issue(task.id)
                _get_issue_time_epic(issue, dict_es)
                _get_issue_time(issue, versions_dict)
            except:
                exceptions.append(task)

        threads.append(
            threading.Thread(
                target=_calculate,
                args=(task, dict_es, versions_dict, sleep)
            )
        )

        sleep += 0.95

    for trd in threads: trd.start()
    for trd in threads: trd.join()

    time_data = []
    for key, value in versions_dict.items():
        time_data.append('{0} - {1}'.format(key, calculate_days(value)))

    epics_dict = {}
    for key, value in dict_es.items():
        if key != "No Epic":
            epic = jira.issue(key)
        else:
            epic = None

        time_data_epic = []
        for k, v in value.items():
            time_data_epic.append('{0} - {1}'.format(k, calculate_days(v)))

        if epic:
            epics_dict[epic.fields.summary] = time_data_epic
        else:
            epics_dict["No Epic"] = time_data_epic

    return time_data, epics_dict




    # incompleted_bissues(oard_id, sprint_id)

    # sprints

    # projects = jira.projects()


# issue.update(timespent=20000)


if __name__ == '__main__':

    # sync_work_log("NSYNC.XHT", "XHT-")
    # sync_work_log("MEV.TP", "TP-")
    sync_work_log("P4V.SOW6", "RPE-")

    # x, y = get_estimates()
    # for k, v in y.items():
    #     print("{0} - {1}".format(k, v))
    # print(x)
