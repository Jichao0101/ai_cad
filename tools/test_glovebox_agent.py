"""Transport-isolated tests of model adapter outcome propagation (no CAD/network)."""
import contextlib
import importlib.util
import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

spec = importlib.util.spec_from_file_location("agent", Path(__file__).with_name("glovebox_agent.py"))
agent = importlib.util.module_from_spec(spec)
spec.loader.exec_module(agent)

class Output(io.StringIO):
    def reconfigure(self, **kwargs):
        pass

class OutcomeTest(unittest.TestCase):
    def invoke(self, status):
        call = {"id":"call-1","type":"function","function":{"name":"run_glovebox","arguments":'{"radius_candidates_mm":[5.0]}'}}
        messages = [{"role":"assistant","content":None,"tool_calls":[call]}, {"role":"assistant","content":"Outcome summary"}]
        responses = [io.BytesIO(json.dumps({"choices":[{"message":m}]}).encode()) for m in messages]
        opener = MagicMock()
        opener.open.side_effect = responses
        result = {"status":status,"run_dir":"test-only","ds_status":"not_evaluated","attempts":[]}
        argv = ["agent", "Build pad", "--radius-min","5","--radius-max","5.5","--minimum-volume","1300","--check-source","test"]
        with patch.object(sys,"argv",argv), patch.object(agent,"load_env"), patch.dict(os.environ,{"QWEN_BASE_URL":"http://127.0.0.1:9999/v1","QWEN_MODEL":"test","QWEN_API_KEY":""}), patch.object(agent.urllib.request,"build_opener",return_value=opener), patch.object(agent.pipeline,"run",return_value=result), patch.object(agent.pipeline,"write_json"), contextlib.redirect_stdout(Output()) as output:
            code = agent.main()
        return code,json.loads(output.getvalue())

    def test_no_solution_is_nonzero(self):
        code,result = self.invoke("no_solution")
        self.assertEqual(code,2)
        self.assertEqual(result["cad_status"],"no_solution")

    def test_passed_is_zero(self):
        code,result = self.invoke("passed")
        self.assertEqual(code,0)
        self.assertEqual(result["cad_status"],"passed")

if __name__ == "__main__":
    unittest.main()
