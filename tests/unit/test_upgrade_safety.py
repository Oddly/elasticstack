import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit

import yaml


ROOT = Path(__file__).resolve().parents[2]
ANSIBLE = shutil.which('ansible-playbook')


@unittest.skipUnless(ANSIBLE, 'ansible-playbook is required')
class TestUpgradeSafety(unittest.TestCase):
    def run_case(self, changes=None, variables=None, entry='elasticsearch-rolling-upgrade', count=2, serial=1, check=False, limit=None, role='elasticsearch', strategy='upgrade_safety_mock'):
        with tempfile.TemporaryDirectory(prefix='elasticstack-upgrade-test-') as directory:
            directory = Path(directory)
            collection = directory / 'collections/ansible_collections/oddly/elasticstack'
            collection.parent.mkdir(parents=True)
            if (changes or {}).get('main_through_logging'):
                collection.mkdir()
                shutil.copytree(ROOT / 'roles', collection / 'roles')
                main = collection / 'roles/elasticsearch/tasks/main.yml'
                main.write_text(main.read_text().split('- name: Install logrotate package for Elasticsearch', 1)[0])
            else:
                collection.symlink_to(ROOT, target_is_directory=True)
            names = ['node-alpha', 'node-beta', 'node-gamma'][:count]
            state = {
                'events': [], 'api_writes': [], 'package_writes': [], 'other_writes': [],
                'services': dict.fromkeys(names, 'active'), 'installed': '9.1.1',
                'nodes': names, 'persistent': {}, 'ml_mode': False,
            }
            state.update(changes or {})
            state_path = directory / 'state.json'
            state_path.write_text(json.dumps(state))
            defaults = {}
            for defaults_role in ('elasticstack', 'elasticsearch'):
                defaults.update(yaml.safe_load((ROOT / f'roles/{defaults_role}/defaults/main.yml').read_text()))
            defaults.update({
                'elasticstack_elasticsearch_group_name': 'search_members',
                'elasticstack_release': 9, 'elasticstack_version': '9.1.2',
                'elasticstack_full_stack': False, 'elasticstack_security': True,
                'elasticstack_password': {'stdout': 'fixture-only'}, 'elasticstack_no_log': True,
                'elasticstack_versionseparator': '-' if state.get('os_family') == 'RedHat' else '=',
                'elasticsearch_clustername': 'fixture-cluster',
                'elasticsearch_api_host': 'api.fixture.invalid', 'elasticsearch_validate_api_certs': True,
                'elasticsearch_nodename': '{{ inventory_hostname }}',
                'elasticsearch_upgrade_health_retries': 1, 'elasticsearch_upgrade_health_delay': 0,
                'elasticsearch_upgrade_countdown': 0, 'elasticsearch_heap': '1',
                'elasticsearch_os_tuning': False, 'elasticsearch_pamlimits': False,
                'elasticsearch_logrotate_enabled': False, '_elasticstack_role_imported': True,
                'upgrade_fixture_state': str(state_path),
            })
            if entry != 'main':
                defaults['elasticsearch_package'] = 'elasticsearch' + defaults['elasticstack_versionseparator'] + '9.1.2'
            defaults.update(variables or {})
            if defaults['elasticsearch_api_host'] is None:
                del defaults['elasticsearch_api_host']
            variables_path = directory / 'variables.yml'
            variables_path.write_text(yaml.safe_dump(defaults))
            inventory = {'all': {'children': {'search_members': {'hosts': {
                name: {'ansible_connection': 'local', 'ansible_facts': {
                    'hostname': name, 'os_family': 'Debian', 'distribution_major_version': '13',
                    'memtotal_mb': 2048, 'virtualization_type': 'container',
                }} for name in names
            }}}}}
            inventory_path = directory / 'inventory.yml'
            inventory_path.write_text(yaml.safe_dump(inventory))
            tasks = [{'name': 'Exercise actual task entrypoint', 'ansible.builtin.include_role': {
                'name': f'oddly.elasticstack.{role}', 'tasks_from': entry,
            }}]
            if entry == 'node_maintenance_cycle':
                tasks = [{
                    'name': 'Exercise paired maintenance with cleanup on failure',
                    'block': [{'name': 'Drain node', 'ansible.builtin.include_role': {
                        'name': 'oddly.elasticstack.elasticsearch', 'tasks_from': 'node_maintenance_start',
                    }}],
                    'always': [{'name': 'Restore node', 'ansible.builtin.include_role': {
                        'name': 'oddly.elasticstack.elasticsearch', 'tasks_from': 'node_maintenance_end',
                    }}],
                }]
            elif entry == 'ml_upgrade_retry' or isinstance(entry, tuple):
                steps = entry if isinstance(entry, tuple) else ('ml_upgrade_start', 'ml_upgrade_start', 'ml_upgrade_end')
                tasks = [{'name': 'Exercise ML lifecycle', 'ansible.builtin.include_role': {
                    'name': 'oddly.elasticstack.elasticsearch', 'tasks_from': step,
                }} for step in steps]
            play = [{
                'name': 'Exercise actual Elasticsearch role tasks', 'hosts': 'search_members',
                'gather_facts': True, 'serial': serial, 'any_errors_fatal': True,
                'strategy': strategy,
                'module_defaults': {'ansible.builtin.uri': {'ca_path': '/custom/trust/fixture.pem'}},
                'tasks': tasks,
            }]
            play_path = directory / 'play.yml'
            play_path.write_text(yaml.safe_dump(play))
            config = directory / 'ansible.cfg'
            config.write_text('[defaults]\nhost_key_checking = True\nretry_files_enabled = False\n')
            env = os.environ.copy()
            env.update({
                'ANSIBLE_CONFIG': str(config),
                'ANSIBLE_COLLECTIONS_PATH': str(directory / 'collections') + os.pathsep + os.environ.get('ANSIBLE_COLLECTIONS_PATH', str(Path.home() / '.ansible/collections') + os.pathsep + '/usr/share/ansible/collections'),
                'ANSIBLE_STRATEGY_PLUGINS': str(ROOT / 'tests/plugins/strategy'),
                'ANSIBLE_ACTION_PLUGINS': str(ROOT / 'tests/plugins/action'),
                'ANSIBLE_LOCAL_TEMP': str(directory / 'tmp'),
                'ANSIBLE_NOCOLOR': '1', 'ANSIBLE_LOG_PATH': '/dev/null',
            })
            command = [ANSIBLE, '-i', str(inventory_path), str(play_path), '-e', '@' + str(variables_path)]
            if check:
                command.append('--check')
            if limit:
                command.extend(['--limit', limit])
            completed = subprocess.run(command, env=env, cwd=directory, capture_output=True, text=True, timeout=45)
            return completed, json.loads(state_path.read_text())

    def assert_ok(self, completed):
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def assert_stopped_before_writes(self, completed, state):
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertEqual(state['api_writes'], [])
        self.assertEqual(state['package_writes'], [])
        self.assertEqual(state['other_writes'], [])
        self.assertFalse(any(e['action'] == 'service' for e in state['events']))

    def test_maintenance_restores_all_owned_state_and_declared_baseline(self):
        completed, state = self.run_case(entry='node_maintenance_cycle', count=1, variables={
            'elasticsearch_maintenance_password': 'fixture-only',
            'elasticsearch_cluster_settings': {'indices.recovery.max_bytes_per_sec': '200mb'},
            'elasticsearch_drain_cluster_settings': {
                'indices.recovery.max_bytes_per_sec': '500mb',
                'cluster.routing.allocation.node_concurrent_recoveries': 8,
            },
        })
        self.assert_ok(completed)
        self.assertEqual(state['persistent'], {'indices.recovery.max_bytes_per_sec': '200mb'})
        self.assertEqual(state['voting'], [])
        self.assertFalse(state['ml_mode'])
        self.assertEqual([e['timeout'] for e in state['api_writes'] if e['path'] == '/_ml/set_upgrade_mode'], [180, 180])

    def test_maintenance_restores_nested_and_dotted_recovery_baselines(self):
        baselines = [
            {'indices.recovery.max_bytes_per_sec': '200mb', 'indices.recovery.use_snapshots': False},
            {'indices': {'recovery': {'max_bytes_per_sec': '200mb', 'use_snapshots': False}}},
            {'indices.recovery': {'max_bytes_per_sec': '200mb'}, 'indices.recovery.use_snapshots': False},
        ]
        drains = [
            {'indices.recovery.max_bytes_per_sec': '500mb', 'indices.recovery.use_snapshots': True},
            {'indices': {'recovery': {'max_bytes_per_sec': '500mb', 'use_snapshots': True}}},
            {'indices.recovery': {'max_bytes_per_sec': '500mb'}, 'indices.recovery.use_snapshots': True},
        ]
        initial = {
            'indices.recovery.max_bytes_per_sec': '200mb', 'indices.recovery.use_snapshots': 'false',
            'indices.recovery.max_concurrent_file_chunks': '2',
        }
        for baseline in baselines:
            for drain in drains:
                with self.subTest(baseline=baseline, drain=drain):
                    completed, state = self.run_case({'persistent': initial}, entry='node_maintenance_cycle', count=1, variables={
                        'elasticsearch_maintenance_password': 'fixture-only',
                        'elasticsearch_cluster_settings': baseline,
                        'elasticsearch_drain_cluster_settings': drain | {
                            'cluster.routing.allocation.node_concurrent_recoveries': 8,
                        },
                    })
                    self.assert_ok(completed)
                    self.assertEqual(state['persistent'], initial)
                    self.assertFalse(state['ml_mode'])

    def test_maintenance_preserves_ml_mode_that_was_already_enabled(self):
        completed, state = self.run_case({'ml_mode': True}, entry='node_maintenance_cycle', count=1,
                                         variables={'elasticsearch_maintenance_password': 'fixture-only'})
        self.assert_ok(completed)
        self.assertTrue(state['ml_mode'])
        self.assertFalse(any(e['path'] == '/_ml/set_upgrade_mode' for e in state['api_writes']))

    def test_ml_retry_preserves_pending_original_mode(self):
        for owner in ('node-alpha', 'node-beta'):
            for original in (False, True):
                with self.subTest(owner=owner, original=original):
                    completed, state = self.run_case({'ml_mode': original}, entry='ml_upgrade_retry', limit='node-alpha', variables={
                        'elasticsearch_maintenance_password': 'fixture-only',
                        'elasticsearch_ml_upgrade_state_host': owner,
                    })
                    self.assert_ok(completed)
                    self.assertEqual(state['ml_mode'], original)
                    mutations = [parse_qs(urlsplit(e['url']).query)['enabled']
                                 for e in state['api_writes'] if e['path'] == '/_ml/set_upgrade_mode']
                    self.assertEqual(mutations, [] if original else [['true'], ['false']])

    def test_ml_retry_rejects_pending_state_from_another_cluster(self):
        completed, state = self.run_case(entry='ml_upgrade_start', count=1, variables={
            'elasticsearch_maintenance_password': 'fixture-only',
            '_elasticsearch_ml_upgrade_state': {
                'recorded': True, 'previous': False, 'pending': True, 'cluster_name': 'another-cluster',
            },
        })
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertEqual(state['api_writes'], [])

    def test_ml_lifecycle_rejects_same_name_with_different_or_missing_uuid(self):
        for entry in ('ml_upgrade_start', 'ml_upgrade_end'):
            for uuid in ('another-uuid', None, '', '_na_', 7):
                with self.subTest(entry=entry, uuid=uuid):
                    completed, state = self.run_case({'cluster_uuid': uuid, 'ml_mode': True}, entry=entry, count=1, variables={
                        'elasticsearch_maintenance_password': 'fixture-only',
                        '_elasticsearch_ml_upgrade_state': {
                            'recorded': True, 'previous': False, 'pending': True,
                            'cluster_name': 'fixture-cluster', 'cluster_uuid': 'fixture-uuid',
                        },
                    })
                    self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                    self.assertTrue(state['ml_mode'])
                    self.assertEqual(state['api_writes'], [])

    def test_ml_restore_selects_the_observer_with_the_original_uuid(self):
        completed, state = self.run_case({
            'ml_mode': True, 'cluster_uuid_by_observer': {'node-alpha': 'another-uuid'},
        }, entry='ml_upgrade_end', limit='node-alpha', variables={
            'elasticsearch_maintenance_password': 'fixture-only',
            'elasticsearch_api_host': None,
            'elasticsearch_ml_upgrade_hosts': ['node-alpha', 'node-beta'],
            '_elasticsearch_ml_upgrade_state': {
                'recorded': True, 'previous': False, 'pending': True,
                'cluster_name': 'fixture-cluster', 'cluster_uuid': 'fixture-uuid',
            },
        })
        self.assert_ok(completed)
        self.assertFalse(state['ml_mode'])
        self.assertEqual([e['delegate_to'] for e in state['api_writes']], ['node-beta'])

    def test_ml_mutation_rechecks_uuid_after_observer_selection(self):
        completed, state = self.run_case({
            'ml_mode': True, 'cluster_uuid_by_task': {
                'elasticsearch-ml-upgrade-mode | Verify cluster identity before changing ML mode': 'another-uuid',
            },
        }, entry='ml_upgrade_end', count=1, variables={
            'elasticsearch_maintenance_password': 'fixture-only',
            '_elasticsearch_ml_upgrade_state': {
                'recorded': True, 'previous': False, 'pending': True,
                'cluster_name': 'fixture-cluster', 'cluster_uuid': 'fixture-uuid',
            },
        })
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertTrue(state['ml_mode'])
        self.assertEqual(state['api_writes'], [])

    def test_maintenance_rejects_foreign_or_incomplete_ml_ownership(self):
        records = [
            {'recorded': True, 'previous': True, 'pending': False, 'cluster_name': 'another-cluster', 'cluster_uuid': 'another-uuid'},
            {'recorded': True, 'previous': True, 'pending': False, 'cluster_name': 'fixture-cluster', 'cluster_uuid': 'another-uuid'},
            {'recorded': False, 'previous': True, 'pending': False, 'cluster_name': 'fixture-cluster', 'cluster_uuid': 'fixture-uuid'},
            {'previous': True},
        ]
        for record in records:
            with self.subTest(record=record):
                completed, state = self.run_case({'ml_mode': True}, entry='node_maintenance_end', count=1, variables={
                    'elasticsearch_maintenance_password': 'fixture-only', '_elasticsearch_ml_upgrade_state': record,
                })
                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertTrue(state['ml_mode'])
                self.assertFalse(any(e['path'] == '/_ml/set_upgrade_mode' for e in state['api_writes']))

    def test_ml_end_rejects_a_changed_unowned_original_mode(self):
        completed, state = self.run_case(entry='ml_upgrade_end', count=1, variables={
            'elasticsearch_maintenance_password': 'fixture-only',
            '_elasticsearch_ml_upgrade_state': {
                'recorded': True, 'previous': True, 'pending': False,
                'cluster_name': 'fixture-cluster', 'cluster_uuid': 'fixture-uuid',
            },
        })
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertEqual(state['api_writes'], [])
        self.assertFalse(state['ml_mode'])

    def test_completed_ml_ownership_is_not_reused_by_defensive_cleanup(self):
        completed, state = self.run_case({'ml_mode': True}, count=1,
                                         entry=('ml_upgrade_start', 'ml_upgrade_end', 'node_maintenance_end'), variables={
                                             'elasticsearch_maintenance_password': 'fixture-only',
                                         })
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertIn('ML mode is not restored, or ownership is unknown', completed.stdout)
        self.assertTrue(state['ml_mode'])
        self.assertFalse(any(e['path'] == '/_ml/set_upgrade_mode' for e in state['api_writes']))

    def test_maintenance_accepts_uppercase_cluster_allocation(self):
        for source in ('persistent', 'transient'):
            with self.subTest(source=source):
                changes = {source: {'cluster.routing.allocation.enable': 'ALL'}}
                if source == 'persistent':
                    changes['maintenance_no_apply'] = 'allocation'
                completed, state = self.run_case(changes, entry='node_maintenance_end', count=1, variables={
                    'elasticsearch_maintenance_password': 'fixture-only',
                })
                self.assert_ok(completed)
                self.assertFalse(state['ml_mode'])

    def test_maintenance_checks_elected_master_allocation_settings(self):
        for allocation in ('all', 'ALL', 'aLl', 'primaries', None):
            with self.subTest(allocation=allocation):
                settings = {'cluster.routing.allocation.enable': allocation} if allocation else {}
                completed, state = self.run_case({
                    'defaults': {'cluster.routing.allocation.enable': 'all'}, 'master_settings': settings,
                }, entry='node_maintenance_cycle', variables={'elasticsearch_maintenance_password': 'fixture-only'})
                if allocation == 'primaries':
                    self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                    self.assertFalse(any(e['host'] == 'node-beta' for e in state['events']))
                else:
                    self.assert_ok(completed)
                self.assertFalse(state['ml_mode'])
                readbacks = [e for e in state['events'] if e.get('path') == '/_nodes/_master/settings']
                self.assertTrue(readbacks)
                self.assertTrue(all(parse_qs(urlsplit(e['url']).query).get('flat_settings') == ['true']
                                    for e in readbacks))

    def test_maintenance_rejects_missing_ambiguous_or_failed_master_settings(self):
        responses = [
            {},
            {'_nodes': {'total': 1, 'successful': 1, 'failed': 0}, 'nodes': {
                'master-a': {'settings': {}}, 'master-b': {'settings': {}},
            }},
            {'_nodes': {'total': 1, 'successful': 0, 'failed': 1}, 'nodes': {'master': {'settings': {}}}},
            {'_nodes': {'total': 1, 'successful': 1, 'failed': 0}, 'nodes': {'master': {}}},
        ]
        for response in responses:
            with self.subTest(response=response):
                completed, state = self.run_case({'master_settings_response': response},
                                                 entry='node_maintenance_cycle', variables={
                                                     'elasticsearch_maintenance_password': 'fixture-only',
                                                 })
                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertFalse(state['ml_mode'])
                self.assertFalse(any(e['host'] == 'node-beta' for e in state['events']))

    def test_maintenance_accepts_boolean_recovery_baselines(self):
        for baseline in (False, True):
            with self.subTest(baseline=baseline):
                key = 'indices.recovery.use_snapshots'
                completed, state = self.run_case({'transient': {key: str(baseline).lower()}},
                                                 entry='node_maintenance_cycle', count=1, variables={
                                                     'elasticsearch_maintenance_password': 'fixture-only',
                                                     'elasticsearch_cluster_settings': {key: baseline},
                                                     'elasticsearch_drain_cluster_settings': {key: not baseline},
                                                 })
                self.assert_ok(completed)
                self.assertEqual(state['persistent'][key], str(baseline).lower())
                self.assertFalse(state['ml_mode'])

    def test_maintenance_rejects_conflicting_transient_boolean_recovery_settings(self):
        for baseline in (False, True):
            with self.subTest(baseline=baseline):
                key = 'indices.recovery.use_snapshots'
                completed, state = self.run_case({'transient': {key: str(not baseline).lower()}},
                                                 entry='node_maintenance_cycle', variables={
                                                     'elasticsearch_maintenance_password': 'fixture-only',
                                                     'elasticsearch_cluster_settings': {key: baseline},
                                                     'elasticsearch_drain_cluster_settings': {key: not baseline},
                                                 })
                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertEqual(state['persistent'][key], str(baseline).lower())
                self.assertFalse(state['ml_mode'])
                self.assertFalse(any(e['host'] == 'node-beta' for e in state['events']))

    def test_maintenance_attempts_other_cleanup_after_each_failed_step(self):
        for step in ('allocation', 'voting', 'baseline'):
            with self.subTest(step=step):
                completed, state = self.run_case({'maintenance_failure': step}, entry='node_maintenance_cycle', variables={
                    'elasticsearch_maintenance_password': 'fixture-only',
                    'elasticsearch_cluster_settings': {'indices.recovery.max_bytes_per_sec': '200mb'},
                    'elasticsearch_drain_cluster_settings': {'indices.recovery.max_bytes_per_sec': '500mb'},
                })
                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertFalse(state['ml_mode'])
                attempts = [e['task'] for e in state['api_writes'] if e['task'].startswith('node_maintenance_end |')]
                for task in ('Re-enable shard allocation', 'Clear voting config exclusions', 'Restore recovery settings to the baseline'):
                    self.assertTrue(any(task in name for name in attempts), attempts)
                self.assertFalse(any(e['host'] == 'node-beta' for e in state['events']))

    def test_maintenance_rejects_acknowledged_but_unrestored_state_even_when_green(self):
        for step in ('allocation', 'voting', 'baseline'):
            with self.subTest(step=step):
                completed, state = self.run_case({'maintenance_no_apply': step}, entry='node_maintenance_cycle', variables={
                    'elasticsearch_maintenance_password': 'fixture-only',
                    'elasticsearch_cluster_settings': {'indices.recovery.max_bytes_per_sec': '200mb'},
                    'elasticsearch_drain_cluster_settings': {'indices.recovery.max_bytes_per_sec': '500mb'},
                })
                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertFalse(state['ml_mode'])
                self.assertFalse(any(e['host'] == 'node-beta' for e in state['events']))

    def test_maintenance_check_mode_skips_verification_of_unexecuted_cleanup(self):
        for wait_health in (False, True):
            with self.subTest(wait_health=wait_health):
                completed, state = self.run_case(entry='node_maintenance_end', count=1, check=True,
                                                 strategy='linear', variables={
                                                     'elasticsearch_maintenance_password': 'fixture-only',
                                                     'elasticsearch_maintenance_wait_health': wait_health,
                                                     'elasticsearch_cluster_settings': {'indices.recovery.max_bytes_per_sec': '200mb'},
                                                     'elasticsearch_drain_cluster_settings': {'indices.recovery.max_bytes_per_sec': '500mb'},
                                                 })
                self.assert_ok(completed)
                self.assertEqual(state['api_writes'], [])
                self.assertEqual(state['package_writes'], [])
                self.assertEqual(state['other_writes'], [])

    def test_maintenance_rejects_persistent_allocation_hidden_by_a_transient_override(self):
        completed, state = self.run_case({
            'transient': {'cluster.routing.allocation.enable': 'ALL'},
            'maintenance_no_apply': 'allocation',
        }, entry='node_maintenance_cycle', variables={
            'elasticsearch_maintenance_password': 'fixture-only',
        })
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertEqual(state['persistent']['cluster.routing.allocation.enable'], 'primaries')
        self.assertFalse(state['ml_mode'])
        self.assertFalse(any(e['host'] == 'node-beta' for e in state['events']))

    def test_maintenance_unreachable_allocation_cleanup_still_restores_ml(self):
        completed, state = self.run_case({'cleanup_unreachable_tasks': ['Re-enable shard allocation']},
                                         entry='node_maintenance_cycle', variables={
                                             'elasticsearch_maintenance_password': 'fixture-only',
                                         })
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertFalse(state['ml_mode'])
        self.assertEqual(state['voting'], [])
        self.assertFalse(any(e['host'] == 'node-beta' for e in state['events']))

    def test_defensive_maintenance_does_not_claim_an_unknown_ml_pause(self):
        completed, state = self.run_case({'ml_mode': True}, entry='node_maintenance_end', variables={
            'elasticsearch_maintenance_password': 'fixture-only',
        })
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertTrue(state['ml_mode'])
        self.assertFalse(any(e['path'] == '/_ml/set_upgrade_mode' for e in state['api_writes']))
        self.assertFalse(any(e['host'] == 'node-beta' for e in state['events']))

    def test_maintenance_can_leave_ml_lifecycle_to_the_cluster_orchestrator(self):
        completed, state = self.run_case({'ml_mode': True}, entry='node_maintenance_cycle', count=1, variables={
            'elasticsearch_maintenance_password': 'fixture-only', 'elasticsearch_maintenance_manage_ml': False,
        })
        self.assert_ok(completed)
        self.assertTrue(state['ml_mode'])
        self.assertFalse(any(e['path'].startswith('/_ml/') for e in state['events'] if e['action'] == 'uri'))

    def test_rolling_upgrade_can_skip_ml_maintenance(self):
        for original in (False, True):
            with self.subTest(original=original):
                completed, state = self.run_case({'api_failure': '/_ml/info', 'ml_mode': original}, count=1,
                                                 variables={'elasticsearch_maintenance_manage_ml': False})
                self.assert_ok(completed)
                self.assertEqual(state['ml_mode'], original)
                self.assertFalse(any(e['path'].startswith('/_ml/') for e in state['events'] if e['action'] == 'uri'))
                self.assertEqual(state['package_writes'], ['node-alpha'])
                self.assertEqual(state['services']['node-alpha'], 'active')
                self.assertEqual(state['persistent'], {})
                paths = [e['path'] for e in state['events'] if e['action'] == 'uri']
                self.assertIn('/', paths)
                self.assertIn('/_cluster/health', paths)
                self.assertIn('/_nodes/node-alpha', paths)
                self.assertEqual([e['path'] for e in state['api_writes']], ['/_cluster/settings', '/_flush', '/_cluster/settings'])

    def test_skipping_ml_maintenance_preserves_failed_upgrade_cleanup(self):
        completed, state = self.run_case({'package_failure': True, 'ml_mode': True},
                                         variables={'elasticsearch_maintenance_manage_ml': False})
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertEqual(state['persistent'], {})
        self.assertTrue(state['ml_mode'])
        self.assertFalse(any(e['path'].startswith('/_ml/') for e in state['events'] if e['action'] == 'uri'))
        self.assertIn('elasticsearch-rolling-upgrade | Update Elasticsearch', completed.stdout)
        self.assertFalse(any(e['host'] == 'node-beta' for e in state['events']))

    def test_two_nodes_use_checked_stop_install_start_and_restore(self):
        completed, state = self.run_case()
        self.assert_ok(completed)
        self.assertEqual(state['package_writes'], state['nodes'])
        self.assertEqual(state['persistent'], {})
        self.assertFalse(state['ml_mode'])
        for host in state['nodes']:
            events = [e for e in state['events'] if e['host'] == host]
            stop = next(i for i, e in enumerate(events) if e['action'] == 'service' and e['state'] == 'stopped')
            install = next(i for i, e in enumerate(events) if e['action'] == 'package')
            start = next(i for i, e in enumerate(events) if e['action'] == 'service' and e['state'] == 'started')
            self.assertLess(stop, install)
            self.assertLess(install, start)
            self.assertTrue(all(e['validate_certs'] for e in events if e['action'] == 'uri'))
            self.assertTrue(all(e['ca_path'] == '/custom/trust/fixture.pem' for e in events if e['action'] == 'uri'))

    def test_single_node_has_the_same_checks_and_explicit_restart(self):
        completed, state = self.run_case(count=1)
        self.assert_ok(completed)
        self.assertEqual(state['package_writes'], ['node-alpha'])
        self.assertEqual(state['persistent'], {})

    def test_singleton_activates_logging_written_after_upgrade(self):
        completed, state = self.run_case({'main_through_logging': True, 'logging_changed': True},
                                         entry='main', count=1, variables={'elasticsearch_manage_logging': True})
        self.assert_ok(completed)
        self.assertEqual(state['logging_config'], 1)
        self.assertEqual(state['running_logging'], state['logging_config'])
        events = state['events']
        logging = next(i for i, event in enumerate(events) if event['task'] == 'Configure Elasticsearch logging')
        restart = next(i for i, event in enumerate(events) if event['action'] == 'service' and event['state'] == 'restarted')
        self.assertLess(logging, restart)
        self.assertEqual([e['state'] for e in events if e['action'] == 'service'], ['stopped', 'started', 'restarted'])
        self.assertEqual(state['persistent'], {})
        self.assertFalse(state['ml_mode'])

    def test_unchanged_singleton_logging_does_not_restart_again(self):
        completed, state = self.run_case({'main_through_logging': True}, entry='main', count=1,
                                         variables={'elasticsearch_manage_logging': True})
        self.assert_ok(completed)
        self.assertEqual([e['state'] for e in state['events'] if e['action'] == 'service'], ['stopped', 'started'])
        self.assertEqual(state['running_logging'], 0)

    def test_singleton_post_upgrade_handler_failure_remains_fatal(self):
        completed, state = self.run_case({
            'main_through_logging': True, 'logging_changed': True, 'handler_restart_failure': True,
        }, entry='main', count=1, variables={'elasticsearch_manage_logging': True})
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertIn('simulated handler restart failure', completed.stdout)
        self.assertEqual(state['running_logging'], 0)
        self.assertEqual(state['logging_config'], 1)
        self.assertEqual(state['persistent'], {})
        self.assertFalse(state['ml_mode'])

    def test_multinode_post_upgrade_handler_suppression_is_unchanged(self):
        completed, state = self.run_case({'main_through_logging': True, 'logging_changed': True},
                                         entry='main', count=2, limit='node-alpha',
                                         variables={'elasticsearch_manage_logging': True})
        self.assert_ok(completed)
        self.assertEqual([e['state'] for e in state['events'] if e['action'] == 'service'], ['stopped', 'started'])
        self.assertEqual(state['package_writes'], ['node-alpha'])

    def test_unexpectedly_stopped_node_is_not_upgraded(self):
        completed, state = self.run_case({'services': {'node-alpha': 'inactive', 'node-beta': 'active'}})
        self.assert_stopped_before_writes(completed, state)

    def test_unhealthy_cluster_stops_before_writes(self):
        completed, state = self.run_case({'health': 'red'})
        self.assert_stopped_before_writes(completed, state)

    def test_parallel_batch_is_rejected(self):
        completed, state = self.run_case(serial=2)
        self.assert_stopped_before_writes(completed, state)

    def test_api_failures_stop_immediately(self):
        for failure in ('tls', 'timeout', '503'):
            with self.subTest(failure=failure):
                completed, state = self.run_case({'api_failure': failure})
                self.assert_stopped_before_writes(completed, state)
                self.assertEqual(sum(e['action'] == 'uri' for e in state['events']), 1)

    def test_transient_allocation_override_is_not_overwritten(self):
        completed, state = self.run_case({'transient': {'cluster.routing.allocation.enable': 'none'}})
        self.assert_stopped_before_writes(completed, state)

    def test_wrong_running_version_stops_the_next_node(self):
        completed, state = self.run_case({'running_version': '9.1.1'})
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertEqual(state['package_writes'], ['node-alpha'])
        self.assertEqual(state['persistent'], {})
        self.assertFalse(state['ml_mode'])
        self.assertFalse(any(e['host'] == 'node-beta' for e in state['events']))

    def test_wrong_cluster_is_rejected(self):
        completed, state = self.run_case({'cluster_name': 'some-other-cluster'})
        self.assert_stopped_before_writes(completed, state)

    def test_missing_member_and_incomplete_cluster_are_rejected(self):
        for change in ({'missing_node': True}, {'node_count': 1}):
            with self.subTest(change=change):
                completed, state = self.run_case(change)
                self.assert_stopped_before_writes(completed, state)

    def test_existing_allocation_and_ml_mode_are_preserved(self):
        persistent = {'cluster.routing.allocation.enable': 'all', 'custom.setting': 'keep'}
        completed, state = self.run_case({'persistent': persistent.copy(), 'ml_mode': True})
        self.assert_ok(completed)
        self.assertEqual(state['persistent'], persistent)
        self.assertTrue(state['ml_mode'])
        self.assertFalse(any(e['path'] == '/_ml/set_upgrade_mode' for e in state['api_writes']))

    def test_ml_enable_uses_explicit_server_timeout_and_longer_client_budget(self):
        completed, state = self.run_case(count=1)
        self.assert_ok(completed)
        enables = [e for e in state['api_writes']
                   if e['path'] == '/_ml/set_upgrade_mode' and 'enabled=true' in e['url']]
        self.assertEqual(len(enables), 1)
        enable = enables[0]
        self.assertEqual(parse_qs(urlsplit(enable['url']).query).get('timeout'), ['120s'])
        self.assertEqual(enable['timeout'], 180)
        self.assertEqual(state['package_writes'], ['node-alpha'])
        self.assertEqual(state['persistent'], {})
        self.assertFalse(state['ml_mode'])

    def test_ml_failure_prevents_package_changes(self):
        completed, state = self.run_case({'ml_failure': True})
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertEqual(state['package_writes'], [])
        self.assertEqual(state['persistent'], {})
        self.assertFalse(state['ml_mode'])
        self.assertFalse(any(e['action'] == 'service' for e in state['events']))

    def test_optional_flush_failures_do_not_block_upgrade(self):
        for status in (-1, 409, 503):
            with self.subTest(status=status):
                completed, state = self.run_case({'flush_status': status}, count=1)
                self.assert_ok(completed)
                self.assertEqual(state['package_writes'], ['node-alpha'])
                self.assertEqual(state['persistent'], {})
                self.assertFalse(state['ml_mode'])
                self.assertIn('proceeding without this optional', completed.stdout)

    def test_other_flush_errors_remain_fatal_before_package_changes(self):
        for status in (401, 403, 500):
            with self.subTest(status=status):
                completed, state = self.run_case({'flush_status': status}, count=1)
                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertEqual(state['package_writes'], [])
                self.assertEqual(state['persistent'], {})
                self.assertFalse(state['ml_mode'])
                self.assertFalse(any(e['action'] == 'service' for e in state['events']))

    def test_startup_api_failures_are_retried_until_the_node_rejoins(self):
        for status in (-1, 503):
            for count in (1, 2):
                with self.subTest(status=status, count=count):
                    completed, state = self.run_case({'rejoin_statuses': [status, 200]}, count=count)
                    self.assert_ok(completed)
                    self.assertEqual(state['package_writes'], state['nodes'])
                    self.assertEqual(state['rejoin_attempts'], dict.fromkeys(state['nodes'], 2))
                    self.assertEqual(state['persistent'], {})
                    self.assertFalse(state['ml_mode'])

    def test_persistent_startup_api_failures_exhaust_retries_and_stop_the_batch(self):
        for status in (-1, 503):
            with self.subTest(status=status):
                completed, state = self.run_case({'rejoin_statuses': [status]}, variables={
                    'elasticsearch_upgrade_health_retries': 2,
                })
                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertEqual(state['rejoin_attempts'], {'node-alpha': 3})
                self.assertEqual(state['package_writes'], ['node-alpha'])
                self.assertEqual(state['persistent'], {})
                self.assertFalse(state['ml_mode'])
                self.assertFalse(any(e['host'] == 'node-beta' for e in state['events']))

    def test_singleton_molecule_explicitly_allows_yellow_without_changing_the_default(self):
        completed, state = self.run_case({'health': 'yellow'}, count=1)
        self.assert_stopped_before_writes(completed, state)
        scenario = yaml.safe_load((ROOT / 'molecule/elasticsearch_upgrade_8to9_single/converge.yml').read_text())
        upgrade = next(play for play in scenario if play.get('vars', {}).get('elasticstack_release') == 9)
        completed, state = self.run_case({'health': 'yellow', 'post_health': 'yellow'}, count=1, variables={
            'elasticsearch_upgrade_wait_status': upgrade['vars'].get('elasticsearch_upgrade_wait_status', 'green'),
        })
        self.assert_ok(completed)
        self.assertEqual(state['package_writes'], ['node-alpha'])
        self.assertEqual(state['persistent'], {})
        self.assertFalse(state['ml_mode'])

    def test_rpm_preview_and_rolling_install_match_the_shared_installer(self):
        for full_stack, manage_repositories in ((True, True), (True, False), (False, True), (False, False)):
            with self.subTest(full_stack=full_stack, manage_repositories=manage_repositories):
                variables = {
                    'elasticstack_version': 'latest', 'elasticstack_full_stack': full_stack,
                    'elasticstack_enable_repos': manage_repositories,
                }
                completed, state = self.run_case({'os_family': 'RedHat', 'candidate_requires_repository': True,
                                                   'candidate_repository': ['elastic-9.x'] if manage_repositories else None},
                                                 entry='main', count=1, variables=variables)
                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertTrue(any(e.get('boundary') for e in state['events']), completed.stdout + completed.stderr)
                self.assertEqual(state['package_writes'], ['node-alpha'])
                packages = [e for e in state['events'] if e['action'] == 'package' and e['name'] == 'elasticsearch']
                self.assertEqual([e['check_mode'] for e in packages], [True, False])
                self.assertTrue(all(e['enablerepo'] == (['elastic-9.x'] if manage_repositories else None) for e in packages))
        completed, state = self.run_case({'os_family': 'RedHat', 'installed': ''}, entry='main', count=1, variables={
            'elasticstack_version': 'latest', 'elasticstack_full_stack': False, 'elasticstack_enable_repos': False,
        })
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertTrue(any(e.get('boundary') for e in state['events']), completed.stdout + completed.stderr)
        package = next(e for e in state['events'] if e['action'] == 'package' and e['name'] == 'elasticsearch')
        self.assertIsNone(package['enablerepo'])
        self.assertFalse(package['check_mode'])

    def test_shared_rpm_installer_respects_external_repository_management(self):
        for full_stack in (True, False):
            for manage_repositories in (True, False):
                for version in ('9.1.2', 'latest'):
                    with self.subTest(full_stack=full_stack, manage_repositories=manage_repositories, version=version):
                        name = 'kibana' if version == 'latest' else 'kibana-9.1.2'
                        completed, state = self.run_case({'os_family': 'RedHat'}, count=1,
                            role='elasticstack', entry='install_elastic_package', variables={
                                'elasticstack_full_stack': full_stack,
                                'elasticstack_enable_repos': manage_repositories,
                                'elasticstack_version': version,
                                '_package_name': name, '_package_base_name': 'kibana',
                            })
                        self.assert_ok(completed)
                        packages = [e for e in state['events'] if e['action'] == 'package']
                        self.assertEqual(len(packages), 1)
                        self.assertEqual(packages[0]['name'], name)
                        self.assertEqual(packages[0]['enablerepo'], ['elastic-9.x'] if manage_repositories else None)

    def test_beats_rpm_installer_respects_external_repository_management(self):
        for full_stack in (True, False):
            for manage_repositories in (True, False):
                for version in ('9.1.2', 'latest'):
                    with self.subTest(full_stack=full_stack, manage_repositories=manage_repositories, version=version):
                        completed, state = self.run_case({'os_family': 'RedHat'}, count=1,
                            role='beats', entry='beat-install', variables={
                                'elasticstack_full_stack': full_stack,
                                'elasticstack_enable_repos': manage_repositories,
                                'elasticstack_version': version, '_beat_name': 'filebeat',
                            })
                        self.assert_ok(completed)
                        packages = [e for e in state['events'] if e['action'] == 'package']
                        self.assertEqual(len(packages), 2 if version == 'latest' else 1)
                        expected = ['elastic-9.x'] if full_stack and manage_repositories else None
                        self.assertTrue(all(e['enablerepo'] == expected for e in packages))

    def test_bad_rpm_repository_fails_preview_before_elasticsearch_changes(self):
        for failure in ('missing', 'unusable'):
            with self.subTest(failure=failure):
                completed, state = self.run_case({'os_family': 'RedHat', 'repository_failure': failure},
                                                 entry='main', count=1, variables={
                    'elasticstack_version': 'latest', 'elasticstack_full_stack': False, 'elasticstack_enable_repos': False,
                })
                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertIn('simulated unavailable repository', completed.stdout)
                self.assertEqual(state['package_writes'], [])
                self.assertEqual(state['api_writes'], [])
                self.assertFalse(any(e['action'] == 'service' for e in state['events']))
                self.assertFalse(any(e['action'] == 'template' for e in state['events']))
                self.assertFalse(any(e.get('boundary') for e in state['events']))
                self.assertTrue(any(e['action'] == 'package' and e.get('name') == 'openssl' for e in state['other_writes']))

    def test_failed_upgrade_does_not_continue_to_the_second_node(self):
        completed, state = self.run_case({'package_failure': True})
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertFalse(any(e['host'] == 'node-beta' for e in state['events']))
        self.assertEqual(state['persistent'], {})
        self.assertFalse(state['ml_mode'])

    def test_ml_restore_retries_a_timeout_before_continuing(self):
        completed, state = self.run_case({'ml_restore_statuses': [-1, 200]})
        self.assert_ok(completed)
        self.assertEqual(state['package_writes'], state['nodes'])
        self.assertEqual(state['ml_restore_attempts'], dict.fromkeys(state['nodes'], 2))
        self.assertFalse(state['ml_mode'])
        restores = [e for e in state['api_writes'] if e['path'] == '/_ml/set_upgrade_mode' and 'enabled=false' in e['url']]
        self.assertTrue(all(e['timeout'] > 60 for e in restores))
        self.assertTrue(all('timeout=120s' in e['url'] for e in restores))

    def test_ml_restore_retries_a_server_failure(self):
        completed, state = self.run_case({'ml_restore_statuses': [500, 200]}, count=1)
        self.assert_ok(completed)
        self.assertEqual(state['ml_restore_attempts'], {'node-alpha': 2})
        self.assertFalse(state['ml_mode'])

    def test_ml_restore_can_confirm_a_change_applied_before_client_timeout(self):
        completed, state = self.run_case({
            'ml_restore_statuses': [-1, 200], 'ml_restore_applied_on_timeout': True,
        }, count=1)
        self.assert_ok(completed)
        self.assertEqual(state['ml_restore_attempts'], {'node-alpha': 2})
        self.assertFalse(state['ml_mode'])

    def test_persistent_ml_restore_failure_stops_the_next_node(self):
        completed, state = self.run_case({'ml_restore_statuses': [503]})
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertIn('Temporary cluster settings could not be restored', completed.stdout)
        self.assertEqual(state['ml_restore_attempts'], {'node-alpha': 3})
        self.assertEqual(state['package_writes'], ['node-alpha'])
        self.assertTrue(state['ml_mode'])
        self.assertFalse(any(e['host'] == 'node-beta' for e in state['events']))

    def test_ml_restore_requires_observed_disabled_mode_not_only_acknowledgement(self):
        completed, state = self.run_case({'ml_restore_does_not_apply': True})
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertIn('Temporary cluster settings could not be restored', completed.stdout)
        self.assertEqual(state['package_writes'], ['node-alpha'])
        self.assertTrue(state['ml_mode'])
        self.assertFalse(any(e['host'] == 'node-beta' for e in state['events']))

    def test_allocation_cleanup_failure_does_not_skip_ml_cleanup(self):
        completed, state = self.run_case({'allocation_restore_failure': True})
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertEqual(state['package_writes'], ['node-alpha'])
        self.assertFalse(state['ml_mode'])
        self.assertFalse(any(e['host'] == 'node-beta' for e in state['events']))

    def test_post_upgrade_bad_health_stops_next_node(self):
        completed, state = self.run_case({'post_health': 'red'})
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertEqual(state['package_writes'], ['node-alpha'])
        self.assertFalse(any(e['host'] == 'node-beta' for e in state['events']))

    def test_check_mode_does_not_mutate(self):
        completed, state = self.run_case(check=True)
        self.assert_ok(completed)
        self.assertEqual(state['api_writes'], [])
        self.assertEqual(state['package_writes'], [])
        self.assertEqual(state['other_writes'], [])

    def test_limit_does_not_reduce_required_cluster_membership(self):
        completed, state = self.run_case(count=3, limit='node-beta')
        self.assert_ok(completed)
        self.assertEqual(state['package_writes'], ['node-beta'])

    def test_main_fails_before_shared_role_writes_when_api_is_broken(self):
        completed, state = self.run_case({'api_failure': '503'}, entry='main', variables={'_elasticstack_role_imported': False})
        self.assert_stopped_before_writes(completed, state)
        self.assertEqual(sum(e['action'] == 'uri' for e in state['events']), 1)

    def test_latest_main_previews_before_a_single_controlled_package_update(self):
        completed, state = self.run_case(entry='main', count=1, variables={'elasticstack_version': 'latest'})
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertTrue(any(e.get('boundary') for e in state['events']), completed.stdout + completed.stderr)
        self.assertEqual(state['package_writes'], ['node-alpha'])
        events = state['events']
        preview = next(i for i, e in enumerate(events) if e['action'] == 'package' and e['name'] == 'elasticsearch' and e['check_mode'])
        stop = next(i for i, e in enumerate(events) if e['action'] == 'service' and e['state'] == 'stopped')
        install = next(i for i, e in enumerate(events) if e['action'] == 'package' and e['name'] == 'elasticsearch' and not e['check_mode'])
        self.assertLess(preview, stop)
        self.assertLess(stop, install)

    def test_latest_noop_does_not_require_a_serial_restart(self):
        completed, state = self.run_case({'candidate': False}, entry='main', serial=2, variables={'elasticstack_version': 'latest'})
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertTrue(any(e.get('boundary') for e in state['events']), completed.stdout + completed.stderr)
        self.assertEqual(state['package_writes'], [])
        self.assertFalse(any(e['action'] == 'service' for e in state['events']))
        self.assertEqual(state['api_writes'], [])

    def test_empty_version_keeps_present_semantics(self):
        completed, state = self.run_case(entry='main', count=1, variables={'elasticstack_version': ''})
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertTrue(any(e.get('boundary') for e in state['events']), completed.stdout + completed.stderr)
        self.assertEqual(state['package_writes'], [])
        self.assertEqual(state['api_writes'], [])
        self.assertFalse(any(e['action'] == 'service' for e in state['events']))
        self.assertFalse(any(e['action'] == 'package' and e['check_mode'] for e in state['events']))

    def test_noop_latest_cannot_update_again_after_preview(self):
        completed, state = self.run_case({'candidate': False, 'candidate_changes_after_preview': True}, entry='main', count=1, variables={'elasticstack_version': 'latest'})
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertTrue(any(e.get('boundary') for e in state['events']), completed.stdout + completed.stderr)
        self.assertEqual(state['package_writes'], [])
        self.assertFalse(any(e['action'] == 'service' for e in state['events']))

    def test_cross_major_api_failure_has_no_skip_exception(self):
        completed, state = self.run_case({'installed': '8.19.4', 'api_failure': '503'})
        self.assert_stopped_before_writes(completed, state)
        self.assertEqual(sum(e['action'] == 'uri' for e in state['events']), 1)

    def test_first_install_is_not_treated_as_stopped_service_recovery(self):
        completed, state = self.run_case({'installed': ''}, entry='main', count=1)
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertTrue(any(e.get('boundary') for e in state['events']), completed.stdout + completed.stderr)
        self.assertEqual(state['package_writes'], ['node-alpha'])
        self.assertFalse(any(e['action'] == 'uri' for e in state['events']))

    def test_custom_observer_and_managed_rpm_repository_are_respected(self):
        completed, state = self.run_case({'os_family': 'RedHat'}, count=1, variables={
            'elasticstack_full_stack': True,
            'elasticsearch_maintenance_api_url': 'https://observer.fixture.invalid:29443',
        })
        self.assert_ok(completed)
        urls = [urlsplit(e['url']) for e in state['events'] if e['action'] == 'uri']
        self.assertTrue(urls)
        for url in urls:
            self.assertEqual(url.scheme, 'https')
            self.assertEqual(url.netloc, 'observer.fixture.invalid:29443')
        packages = [e for e in state['events'] if e['action'] == 'package']
        self.assertEqual(packages[0]['enablerepo'], ['elastic-9.x'])

    def test_healthy_local_cleanup_does_not_connect_to_an_unreachable_peer(self):
        completed, state = self.run_case({'cleanup_unreachable_hosts': ['node-beta']}, limit='node-alpha')
        self.assert_ok(completed)
        self.assertEqual(state['package_writes'], ['node-alpha'])
        self.assertEqual(state['persistent'], {})
        self.assertFalse(state['ml_mode'])
        cleanup = [e for e in state['events'] if 'elasticsearch-upgrade-restore |' in e['task']]
        cleanup += [e for e in state['events']
                    if e['task'].startswith('elasticsearch-ml-upgrade-mode |') and e['delegate_to']]
        self.assertEqual(len(cleanup), 5)
        self.assertTrue(all(e['delegate_to'] == 'node-alpha' for e in cleanup))

    def test_unreachable_local_cleanup_can_fall_back_to_a_peer(self):
        completed, state = self.run_case({'cleanup_unreachable_hosts': ['node-alpha']}, limit='node-alpha')
        self.assert_ok(completed)
        self.assertEqual(state['persistent'], {})
        self.assertFalse(state['ml_mode'])
        identities = [e for e in state['events'] if 'cleanup cluster identity' in e['task']]
        self.assertEqual([e['delegate_to'] for e in identities], ['node-alpha', 'node-beta'])
        restores = [e for e in state['api_writes']
                    if 'Restore ' in e['task'] or (e['path'] == '/_ml/set_upgrade_mode' and 'enabled=false' in e['url'])]
        self.assertEqual([e['delegate_to'] for e in restores], ['node-beta', 'node-beta'])

    def test_failed_cleanup_peer_remains_fatal_with_original_upgrade_failure(self):
        for failure in ('unreachable', 'api'):
            with self.subTest(failure=failure):
                changes = {'package_failure': True}
                changes.update({'cleanup_unreachable_hosts': ['node-beta']} if failure == 'unreachable' else {'cleanup_api_down': True})
                completed, state = self.run_case(changes, variables={'elasticsearch_api_host': None})
                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertIn('Temporary cluster settings could not be restored', completed.stdout)
                self.assertIn('elasticsearch-rolling-upgrade | Update Elasticsearch', completed.stdout)
                self.assertEqual(state['persistent'], {'cluster.routing.allocation.enable': 'primaries'})
                self.assertTrue(state['ml_mode'])
                self.assertFalse(any('Restore ' in e['task'] for e in state['api_writes']))
                self.assertFalse(any(e['host'] == 'node-beta' for e in state['events']))
                identities = [e for e in state['events'] if 'cleanup cluster identity' in e['task']]
                self.assertEqual([e['delegate_to'] for e in identities], ['node-alpha', 'node-beta'])

    def test_unreachable_allocation_cleanup_does_not_skip_ml_cleanup(self):
        completed, state = self.run_case({'cleanup_unreachable_tasks': ['Restore allocation setting']})
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        self.assertIn('Temporary cluster settings could not be restored', completed.stdout)
        self.assertEqual(state['persistent'], {'cluster.routing.allocation.enable': 'primaries'})
        self.assertFalse(state['ml_mode'])
        restore_tasks = [e['task'] for e in state['events']
                         if 'Restore ' in e['task'] or (e.get('path') == '/_ml/set_upgrade_mode' and 'enabled=false' in e['url'])]
        self.assertEqual(restore_tasks, [
            'elasticsearch-upgrade-restore | Restore allocation setting',
            'elasticsearch-ml-upgrade-mode | Set ML upgrade mode',
        ])
        self.assertFalse(any(e['host'] == 'node-beta' for e in state['events']))

    def test_unreachable_ml_cleanup_remains_fatal_with_original_failure(self):
        for task in ('Set ML upgrade mode', 'Verify ML upgrade mode'):
            with self.subTest(task=task):
                completed, state = self.run_case({'package_failure': True, 'cleanup_unreachable_tasks': [task]})
                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertIn('Temporary cluster settings could not be restored', completed.stdout)
                self.assertIn('elasticsearch-rolling-upgrade | Update Elasticsearch', completed.stdout)
                self.assertFalse(any(e['host'] == 'node-beta' for e in state['events']))

    def test_default_cleanup_api_uses_another_configured_cluster_member(self):
        completed, state = self.run_case({'package_failure': True}, variables={'elasticsearch_api_host': None})
        self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
        cleanup = [e for e in state['events'] if e['action'] == 'uri' and 'cleanup cluster identity' in e['task']]
        self.assertEqual([event['delegate_to'] for event in cleanup], ['node-alpha', 'node-beta'])
        self.assertTrue(all(event['url'] == 'https://localhost:9200/' for event in cleanup))
        self.assertEqual(state['persistent'], {})
        self.assertFalse(state['ml_mode'])

    def test_missing_or_uncommitted_cluster_uuid_stops_before_upgrade_writes(self):
        for uuid in (None, '', '_na_', False):
            with self.subTest(uuid=uuid):
                completed, state = self.run_case({'cluster_uuid': uuid}, count=1)
                self.assert_stopped_before_writes(completed, state)

    def test_unknown_cleanup_cluster_is_not_modified(self):
        for change in ('wrong_cleanup_cluster', 'wrong_cleanup_uuid'):
            with self.subTest(change=change):
                completed, state = self.run_case({change: True})
                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertEqual(state['package_writes'], ['node-alpha'])
                self.assertFalse(any('Restore ' in e['task'] for e in state['api_writes']))
                self.assertFalse(any(e['path'] == '/_ml/set_upgrade_mode' and 'enabled=false' in e['url'] for e in state['api_writes']))
                self.assertFalse(any(e['host'] == 'node-beta' for e in state['events']))

    def test_main_rejects_in_place_downgrade_before_writes(self):
        completed, state = self.run_case(entry='main', variables={'elasticstack_version': '9.0.0'})
        self.assert_stopped_before_writes(completed, state)
        self.assertIn('does not support an in-place downgrade', completed.stdout)
