import base64
import fcntl
import json
from pathlib import Path
from urllib.parse import urlsplit

from ansible.plugins.action import ActionBase


class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        super().run(tmp, task_vars)
        path = Path(task_vars['upgrade_fixture_state'])
        with path.open('r+', encoding='utf-8') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            state = json.load(handle)
            result = self.respond(state, task_vars)
            handle.seek(0)
            json.dump(state, handle)
            handle.truncate()
        return result

    def respond(self, state, task_vars):
        action = self._task.args['original_action'].split('.')[-1]
        args = self._task.args['original_args']
        host = task_vars['inventory_hostname']
        event = {
            'action': action,
            'host': host,
            'task': self._task.name,
            'check_mode': self._task.check_mode,
            'delegate_to': self._task.delegate_to,
        }
        state['events'].append(event)
        result = {'changed': False}
        if action in {'setup', 'gather_facts'}:
            result['ansible_facts'] = {
                'ansible_hostname': host, 'ansible_os_family': state.get('os_family', 'Debian'),
                'ansible_distribution_major_version': '13', 'ansible_memtotal_mb': 2048,
                'ansible_virtualization_type': 'container',
            }
        elif action == 'systemd' and 'name' in args:
            result['status'] = {'ActiveState': state['services'][host]}
        elif action == 'service':
            event['state'] = args['state']
            if not self._task.check_mode:
                if args['state'] == 'restarted' and state.get('handler_restart_failure'):
                    return {'changed': False, 'failed': True, 'msg': 'simulated handler restart failure'}
                state['services'][host] = 'inactive' if args['state'] == 'stopped' else 'active'
                if args['state'] in {'started', 'restarted'}:
                    state['running_logging'] = state.get('logging_config', 0)
                result['changed'] = True
        elif action == 'package_facts':
            packages = {'elasticsearch': [{'version': state['installed']}]} if state['installed'] else {}
            result['ansible_facts'] = {'packages': packages}
        elif action == 'package':
            name = str(args['name'])
            event['name'] = name
            event['enablerepo'] = args.get('enablerepo')
            if name.startswith('elasticsearch'):
                if self._task.check_mode and state.get('repository_failure'):
                    return {'changed': False, 'failed': True, 'msg': 'simulated unavailable repository'}
                if state.get('candidate_requires_repository') and args.get('state') == 'latest':
                    result['changed'] = args.get('enablerepo') == ['elastic-9.x']
                else:
                    result['changed'] = state.get('candidate', True)
                if args.get('state') == 'present' and name == 'elasticsearch' and state['installed']:
                    result['changed'] = False
                if self._task.check_mode and state.get('candidate_changes_after_preview'):
                    state['candidate'] = True
                if not self._task.check_mode and result['changed']:
                    if state.get('package_failure'):
                        result.update(failed=True, msg='simulated package failure')
                    else:
                        state['package_writes'].append(host)
            elif not self._task.check_mode:
                state['other_writes'].append(event)
        elif action == 'uri':
            event.update(
                method=args.get('method', 'GET'),
                path=urlsplit(args['url']).path,
                url=args['url'],
                validate_certs=args.get('validate_certs'),
                ca_path=args.get('ca_path'),
                body=args.get('body'),
            )
            observer = event['delegate_to'] or host
            if 'elasticsearch-upgrade-restore |' in event['task']:
                if observer in state.get('cleanup_unreachable_hosts', []):
                    return {'changed': False, 'unreachable': True, 'msg': 'simulated unavailable management connection'}
                if any(name in event['task'] for name in state.get('cleanup_unreachable_tasks', [])):
                    return {'changed': False, 'unreachable': True, 'msg': 'simulated unavailable cleanup connection'}
                if event['method'] == 'GET' and (
                    state.get('cleanup_api_down') or (
                        urlsplit(event['url']).hostname in {'localhost', '127.0.0.1', observer}
                        and state['services'][observer] != 'active'
                    )
                ):
                    return {'changed': False, 'failed': True, 'status': -1, 'msg': 'simulated unavailable cleanup API'}
            return self.api(state, event)
        elif action == 'stat':
            result['stat'] = {'exists': True, 'isreg': True, 'isdir': False, 'mode': '0600'}
        elif action == 'slurp':
            result['content'] = base64.b64encode(b'max').decode()
        elif action in {'command', 'shell'}:
            result.update(rc=0, stdout='', stdout_lines=[], stderr='')
            state['other_writes'].append(event)
        elif action == 'pause':
            pass
        elif action == 'template' and self._task.name == 'Configure Elasticsearch logging':
            result['changed'] = state.get('logging_changed', False) and not self._task.check_mode
            if result['changed']:
                state['logging_config'] = state.get('logging_config', 0) + 1
        elif action == 'template' and self._task.name == 'Configure Elasticsearch' and not state.get('main_through_logging'):
            event['boundary'] = True
            result.update(failed=True, msg='fixture stops after the real main package graph')
        elif self._task.check_mode:
            pass
        else:
            state['other_writes'].append(event)
        return result

    def api(self, state, event):
        path = event['path']
        method = event['method']
        failure = state.get('api_failure')
        if failure and (failure == path or failure in {'tls', 'timeout', '503'}):
            status = -1 if failure in {'tls', 'timeout'} else 503
            return {'changed': False, 'failed': True, 'status': status, 'msg': 'simulated API failure'}
        if method == 'GET':
            if path == '/_cluster/health':
                post = bool(state['package_writes'])
                cleanup = 'cleanup cluster identity' in event['task']
                cluster = 'wrong-cluster' if cleanup and state.get('wrong_cleanup_cluster') else state.get('cluster_name', 'fixture-cluster')
                health = state.get('post_health', 'green') if post else state.get('health', 'green')
                return {'status': 200, 'json': {
                    'status': health,
                    'cluster_name': cluster,
                    'number_of_nodes': state.get('node_count', len(state['nodes'])),
                }, 'changed': False}
            if path == '/_cat/nodes':
                if 'Wait for this node to rejoin' in event['task']:
                    attempts = state.setdefault('rejoin_attempts', {})
                    attempts[event['host']] = attempts.get(event['host'], 0) + 1
                    statuses = state.get('rejoin_statuses', [200])
                    status = statuses[min(attempts[event['host']] - 1, len(statuses) - 1)]
                    if status != 200:
                        return {'changed': False, 'failed': True, 'status': status, 'msg': 'simulated startup API failure'}
                nodes = [] if state.get('missing_node') else state['nodes']
                if state.get('rejoin_failure') and state['package_writes']:
                    nodes = []
                return {'status': 200, 'content': '\n'.join(nodes), 'changed': False}
            if path.startswith('/_nodes/'):
                name = path.split('/')[-1]
                version = state.get('running_version', '9.1.2')
                return {'status': 200, 'json': {'nodes': {name: {'name': name, 'version': version}}}, 'changed': False}
            if path == '/_cluster/settings':
                return {'status': 200, 'json': {'persistent': state['persistent'], 'transient': state.get('transient', {})}, 'changed': False}
            if path == '/_ml/info':
                return {'status': 200, 'json': {'upgrade_mode': state['ml_mode']}, 'changed': False}
            return {'status': 404, 'failed': True, 'msg': 'unhandled mock GET'}
        state['api_writes'].append(event)
        restore = 'Restore ' in event['task']
        if path == '/_cluster/settings':
            if restore and state.get('allocation_restore_failure'):
                return {'status': 503, 'failed': True, 'msg': 'simulated allocation restore failure'}
            body = event['body']
            if isinstance(body, str):
                body = json.loads(body)
            for key, value in body['persistent'].items():
                if value is None:
                    state['persistent'].pop(key, None)
                else:
                    state['persistent'][key] = value
            return {'status': 200, 'json': {'acknowledged': not state.get('unacknowledged_allocation')}, 'changed': True}
        if path == '/_ml/set_upgrade_mode':
            if not restore and state.get('ml_failure'):
                return {'status': 503, 'failed': True, 'msg': 'simulated ML failure'}
            state['ml_mode'] = 'enabled=true' in event['url']
            return {'status': 200, 'json': {'acknowledged': True}, 'changed': True}
        if path == '/_flush':
            status = state.get('flush_status', 200)
            return {'status': status, 'failed': status != 200, 'json': {'_shards': {'failed': 0}}, 'changed': False}
        return {'status': 404, 'failed': True, 'msg': 'unhandled mock mutation'}
