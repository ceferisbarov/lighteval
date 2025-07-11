# MIT License

# Copyright (c) 2025 The HuggingFace Team

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""Usage:
lighteval vllm \
    "pretrained=deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B,dtype=bfloat16,data_parallel_size=8,max_model_length=32768,gpu_memory_utilization=0.8,generation_parameters={temperature:0.6,top_p:0.95}" \
    "extended|lcb:codegeneration|0|0"

lighteval vllm \
    "pretrained=Qwen/Qwen2.5-Coder-3B-Instruct,dtype=bfloat16,data_parallel_size=8,max_model_length=32768,gpu_memory_utilization=0.8,generation_parameters={temperature:0.2,top_p:0.95}" \
    "extended|lcb:codegeneration|0|0"
"""

import json
from typing import Any

import numpy as np
from aenum import extend_enum

from lighteval.metrics.metrics import Metrics, SampleLevelMetric
from lighteval.tasks.extended.lcb.codegen_metrics import (
    codegen_metrics,
    extract_code,
    translate_private_test_cases,
)
from lighteval.tasks.lighteval_task import Doc, LightevalTaskConfig
from lighteval.tasks.requests import SamplingMethod


def prepare_prompt(line: dict[str, Any]) -> str:
    query = "You will be given a question (problem specification) and will generate a correct Python program that matches the specification and passes all tests.\n\n"
    query += f"Question: {line['question_content']}\n\n"
    if starter_code := line.get("starter_code", None):
        query += "You will use the following starter code to write the solution to the problem and enclose your code within delimiters.\n"
        query += f"```python\n{starter_code}\n```\n\n"
    else:
        query += "Read the inputs from stdin solve the problem and write the answer to stdout (do not directly test on the sample inputs). Enclose your code within delimiters as follows. Ensure that when the python program runs, it reads the inputs, runs the algorithm and writes output to STDOUT.\n"
        query += "```python\n# YOUR CODE HERE\n```\n\n"
    return query


def lcb_codegeneration_prompt_fn(line, task_name: str = "lcb:codegeneration") -> Doc:
    # For the prompt we need a more general function that can be used tweaked like in:
    # https://github.com/LiveCodeBench/LiveCodeBench/blob/main/lcb_runner/prompts/code_generation.py
    query = prepare_prompt(line)
    # List of dicts of the form: [{"input": "6\nabc\nacb\nbac\nbca\ncab\ncba\n", "output": "YES\nYES\nYES\nNO\nNO\nYES\n", "testtype": "stdin"}]
    public_test_cases = json.loads(line["public_test_cases"])
    private_test_cases = translate_private_test_cases(line["private_test_cases"])
    inputs = [test["input"] for test in public_test_cases + private_test_cases]
    outputs = [test["output"] for test in public_test_cases + private_test_cases]
    return Doc(
        task_name=task_name,
        query=query,
        choices=[""],
        gold_index=0,
        specific={
            "inputs": inputs,
            "outputs": outputs,
            "fn_name": json.loads(line["metadata"]).get("func_name", None),
        },
    )


def codegen_metric(predictions: list[str], formatted_doc: Doc, **kwargs) -> float:
    """Estimates the Pass@1 metric for the code generation task.
    Extract the code from each prediction, Runs it for each sample and generations,
    and computes the Pass@1 over the outputs.
    """
    # Extract generated code snippets
    generated_code_snippets = [[extract_code(pred) for pred in predictions]]  # noqa: F841
    evaluation_sample = {  # noqa: F841
        "inputs": formatted_doc.specific["inputs"],
        "outputs": formatted_doc.specific["outputs"],
        "fn_name": formatted_doc.specific["fn_name"],
    }
    # This is a list of lists because
    evaluation_sample = [{"input_output": json.dumps(evaluation_sample)}]

    metrics, _ = codegen_metrics(
        evaluation_sample,
        generated_code_snippets,
        k_list=[1],  # Only run for Pass@1
        num_process_evaluate=8,
    )
    return metrics["pass@1"]


lcb_codegen_metric = SampleLevelMetric(
    metric_name="codegen_pass@1:16",  # This is the way of informing the number of generations currently
    category=SamplingMethod.GENERATIVE,
    higher_is_better=True,
    sample_level_fn=codegen_metric,
    corpus_level_fn=np.mean,
)


extend_enum(Metrics, "lcb_codegen_metric", lcb_codegen_metric)

configs = [
    "release_v1",
    "release_v2",
    "release_v3",
    "release_v4",
    "release_v5",
    "release_v6",
    "release_latest",
    "v1",
    "v2",
    "v3",
    "v4",
    "v5",
    "v6",
    "v1_v2",
    "v1_v3",
    "v1_v4",
    "v1_v5",
    "v2_v3",
    "v2_v4",
    "v2_v5",
    "v3_v4",
    "v3_v5",
    "v4_v5",
]

tasks = []

for subset in configs:
    # To keep the base subset as the default, the others are named "lcb:codegeneration_v4", "lcb:codegeneration_v5"... etc
    name = "lcb:codegeneration" if subset == "v4_v5" else f"lcb:codegeneration_{subset}"
    task = LightevalTaskConfig(
        name=name,
        suite=["extended"],
        prompt_function=lcb_codegeneration_prompt_fn,
        hf_repo="livecodebench/code_generation_lite",
        hf_subset=subset,  # https://github.com/LiveCodeBench/LiveCodeBench/tree/main?tab=readme-ov-file#dataset-versions
        hf_avail_splits=["test"],
        evaluation_splits=["test"],
        generation_size=32768,
        metrics=[Metrics.lcb_codegen_metric],
        stop_sequence=[],  # no stop sequence, will use EOS token
        trust_dataset=True,
        version=0,
    )
    tasks.append(task)


TASKS_TABLE = tasks
