from ansible._internal._templating._engine import TemplateEngine
from ansible.executor.module_common import _get_action_arg_defaults
from ansible.plugins.strategy.linear import StrategyModule as LinearStrategy


class StrategyModule(LinearStrategy):
    def _queue_task(self, host, task, task_vars, play_context):
        real_actions = {
            'ansible.builtin.assert',
            'ansible.builtin.debug',
            'ansible.builtin.fail',
            'ansible.builtin.include_role',
            'ansible.builtin.include_tasks',
            'ansible.builtin.include_vars',
            'ansible.builtin.set_fact',
            'ansible.builtin.validate_argument_spec',
        }
        if task.action not in real_actions:
            task = task.copy()
            defaults = _get_action_arg_defaults(task.action, task, TemplateEngine(loader=self._loader, variables=task_vars))
            task.args = {'original_action': task.action, 'original_args': defaults | task.args}
            task.action = 'ansible.legacy.upgrade_safety_mock'
        return super()._queue_task(host, task, task_vars, play_context)
