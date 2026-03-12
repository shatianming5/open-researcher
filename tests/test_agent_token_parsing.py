from open_researcher.agents.base import AgentAdapter


class StubAdapter(AgentAdapter):
    name = "stub"
    command = "echo"

    def build_command(self, program_md, workdir):
        return ["echo", "hello"]

    def run(self, workdir, on_output=None, program_file="program.md", env=None):
        return self._run_process(["echo", "hello"], workdir, on_output)


def test_last_token_metrics_default():
    adapter = StubAdapter()
    assert adapter.last_token_metrics is None


def test_last_token_metrics_after_run(tmp_path):
    adapter = StubAdapter()
    adapter.run(tmp_path)
    # StubAdapter has no token parsing, so metrics remain None
    assert adapter.last_token_metrics is None


def test_try_parse_token_line_default():
    adapter = StubAdapter()
    result = adapter._try_parse_token_line("some output line")
    assert result is None
