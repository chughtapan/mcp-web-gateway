import json
import os
from typing import Union

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.requests import Request

# OpenAI API
from openai import OpenAI
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from utils import change_name, standardize

# Load environment variables
load_dotenv()

user_keys = [line.strip() for line in open("./user_keys.txt", "r")]
rapidapi_keys = [line.strip() for line in open("./rapidapi_keys.txt", "r")]
limiter = Limiter(key_func=get_remote_address)
app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


class Info(BaseModel):
    category: str
    tool_name: str
    api_name: str
    tool_input: Union[str, dict]
    strip: str
    toolbench_key: str


class Info(BaseModel):
    category: str
    tool_name: str
    api_name: str
    tool_input: Union[str, dict]
    strip: str
    toolbench_key: str


def prepare_tool_name_and_url(info):
    category = info.category
    standard_category = category.replace(" ", "_").replace(",", "_").replace("/", "_")
    while " " in standard_category or "," in standard_category:
        standard_category = standard_category.replace(" ", "_").replace(",", "_")
    standard_category = standard_category.replace("__", "_")

    tool_name = info.tool_name
    api_name = change_name(standardize(info.api_name))
    if not tool_name.endswith(f"_for_{standard_category}"):
        tool_name = standardize(info.tool_name)
        code_string = f"""from toolenv.tools.{standard_category}.{tool_name}.api import {api_name}"""
        tool_name += f"_for_{standard_category}"
    else:
        tmp_tool_name = standardize(tool_name.replace(f"_for_{standard_category}", ""))
        code_string = f"""from toolenv.tools.{standard_category}.{tmp_tool_name}.api import {api_name}"""
    return tool_name, standard_category, api_name, code_string


def process_error(response):
    save_cache_flag = False
    switch_flag = False
    if (
        "The request to the API has timed out. Please try again later, or if the issue persists"
        in str(response)
    ):
        return_dict = {
            "error": "API temporarily not working error...",
            "response": response,
        }

    if "Your Client (working) ---> Gateway (working) ---> API (not working)" in str(
        response
    ):
        return_dict = {"error": "API not working error...", "response": response}

    elif "Unauthorized" in str(response) or "unauthorized" in str(response):
        save_cache_flag = True
        return_dict = {"error": "Unauthorized error...", "response": response}

    elif "You are not subscribed to this API." in str(response):
        switch_flag = True
        return_dict = {"error": "Unsubscribed error...", "response": response}

    elif "Too many requests" in str(response):
        switch_flag = True
        return_dict = {"error": "Too many requests error...", "response": response}

    elif "You have exceeded" in str(response) or "you are being rate limited" in str(
        response
    ):
        switch_flag = True
        return_dict = {"error": "Rate limit error...", "response": response}

    elif (
        "Access restricted. Check credits balance or enter the correct API key."
        in str(response)
    ):
        switch_flag = True
        return_dict = {"error": "Rate limit error...", "response": response}

    elif "Oops, an error in the gateway has occurred." in str(response):
        switch_flag = True
        return_dict = {"error": "Gateway error...", "response": response}

    elif "Blocked User. Please contact your API provider." in str(response):
        switch_flag = True
        return_dict = {"error": "Blocked error...", "response": response}

    elif "error" in str(response):
        return_dict = {"error": "Message error...", "response": response}

    else:
        save_cache_flag = True
        return_dict = {"error": "", "response": response}
    return return_dict, save_cache_flag, switch_flag


def run(toolbench_code_string, toolbench_api_name, toolbench_input_params_str):
    # get observation
    success_flag = False
    switch_flag = False
    save_cache = False
    exec(toolbench_code_string)
    try:
        eval_func_str = f"{toolbench_api_name}({toolbench_input_params_str})"
        new_func = eval(eval_func_str)
        response, save_cache, switch_flag = process_error(new_func)
        success_flag = True
    except Exception as e:
        response = {
            "error": f"Function executing {toolbench_code_string} error...\n{e}",
            "response": "",
        }
        save_cache = False
    return success_flag, switch_flag, response, save_cache


def dict_shorten(origin: dict, schema: dict):
    for key, value in list(origin.items()):
        if key not in schema:
            del origin[key]
        else:
            if isinstance(value, dict):
                dict_shorten(value, schema[key])  # schema[key] should be a dict
            elif isinstance(value, list):
                if value:
                    if isinstance(value[0], dict):
                        for item in value:
                            dict_shorten(
                                item, schema[key][0]
                            )  # schema[key] should be a list with only one dict element
    return origin


def observation_shorten(
    schema_path, response_dict, category, tool_name, api_name, strip_method
):
    if strip_method == "filter" or (strip_method == "random" and random.random() > 0.5):
        # print(88)
        if isinstance(response_dict["response"], dict):
            # print(77)
            if os.path.exists(os.path.join(schema_path, category)):
                # print(66)
                if os.path.exists(
                    os.path.join(schema_path, category, tool_name + ".json")
                ):
                    # print(55)
                    schema_dicts = json.load(
                        open(
                            os.path.join(schema_path, category, tool_name + ".json"),
                            "r",
                        )
                    )
                    api_list = schema_dicts["api_list"]
                    schema = None
                    for schema_dict in api_list:
                        schema_api_name = change_name(standardize(schema_dict["name"]))
                        if (
                            schema_api_name == api_name
                            and len(schema_dict["schema"]) > 0
                        ):
                            schema = schema_dict["schema"]
                            break
                    if schema is not None:
                        # print(44)
                        # print(response_dict["response"])
                        response_dict["response"] = dict_shorten(
                            response_dict["response"], schema
                        )
                        # print(999)
                        # print(response_dict["response"])
    return str(response_dict["response"])


@app.post("/rapidapi")
@limiter.limit("999999/minute")
def get_rapidapi_response(request: Request, info: Info):
    user_key = info.toolbench_key
    print("user_key: " + user_key)
    print(info)
    if user_key not in user_keys:
        return {
            "error": "Unauthorized error...",
            "response": "You are not authorized for our rapidapi service. Please fill out our application form and we will process it as soon as possible.",
        }
    tool_name, standard_category, api_name, code_string = prepare_tool_name_and_url(
        info
    )
    tool_input = info.tool_input

    schema_path = "jsons_schema"
    strip_method = info.strip
    if api_name == "chat_with_user":
        return {"error": "", "response": "Chat with user."}

    # load from cache
    cache = {}
    try:
        tool_input = json.loads(tool_input)
    except Exception as e:
        if tool_input == "":
            tool_input = {}
        elif isinstance(tool_input, dict):
            tool_input = tool_input
        else:
            print(f"Can not parse tool input into json: {tool_input}")
            print(type(tool_input))
            print(tool_input)
            response_dict = {"error": f"Tool input parse error...\n", "response": ""}
            return response_dict
    if not os.path.exists("my_tools_cache"):
        os.mkdir("my_tools_cache")

    try:
        if os.path.exists(os.path.join("my_tools_cache/", standard_category)):
            if os.path.exists(
                os.path.join("my_tools_cache/", standard_category, tool_name)
            ):
                if os.path.exists(
                    os.path.join(
                        "my_tools_cache/",
                        standard_category,
                        tool_name,
                        api_name + ".json",
                    )
                ):
                    cache = json.load(
                        open(
                            os.path.join(
                                "my_tools_cache/",
                                standard_category,
                                tool_name,
                                api_name + ".json",
                            ),
                            "r",
                        )
                    )
                    # os.system(f'rm {os.path.join("my_tools_cache/", standard_category, tool_name, api_name+".json")}')
                    if str(tool_input) in cache:
                        response_dict = cache[str(tool_input)]
                        observation = observation_shorten(
                            schema_path,
                            response_dict,
                            standard_category,
                            tool_name.replace(f"_for_{standard_category}", ""),
                            api_name,
                            strip_method,
                        )
                        result = str(observation)[:2048]
                        print("load from cache")
                        print(result[-20:])
                        return {"error": response_dict["error"], "response": result}
    except Exception as e:
        print(f"Loading cache error: {e}")

    input_params_str = ""
    if len(tool_input) > 0:
        for key, value in tool_input.items():
            if isinstance(value, str):
                input_params_str += f'{key}="{value}", '
            else:
                input_params_str += f"{key}={value}, "

    for init_key in rapidapi_keys:
        input_params_str += f"toolbench_rapidapi_key='{init_key}'"
        # get observation
        success_flag, switch_flag, response_dict, save_cache = run(
            code_string, api_name, input_params_str
        )
        if not switch_flag:
            break
        input_params_str = input_params_str[
            : input_params_str.find("toolbench_rapidapi_key=")
        ]

    # save cache
    if save_cache:
        try:
            cache[str(tool_input)] = response_dict
            if not os.path.exists(os.path.join("my_tools_cache/", standard_category)):
                os.mkdir(os.path.join("my_tools_cache/", standard_category))
            if not os.path.exists(
                os.path.join("my_tools_cache/", standard_category, tool_name)
            ):
                os.mkdir(os.path.join("my_tools_cache/", standard_category, tool_name))
            json.dump(
                cache,
                open(
                    os.path.join(
                        "my_tools_cache/",
                        standard_category,
                        tool_name,
                        api_name + ".json",
                    ),
                    "w",
                ),
                indent=4,
            )
        except Exception as e:
            print(f"Save cache failed: {e}")
    cache = None
    observation = observation_shorten(
        schema_path,
        response_dict,
        standard_category,
        tool_name.replace(f"_for_{standard_category}", ""),
        api_name,
        strip_method,
    )
    result = str(observation)[:1500]
    print(result[-20:])
    print(result)
    return {"error": response_dict["error"], "response": result}


@app.post("/fake_rapidapi")
@limiter.limit("999999/minute")
def get_fake_rapidapi_response(request: Request, info: Info):
    print("using fake server")
    user_key = info.toolbench_key

    tool_name, standard_category, api_name, code_string = prepare_tool_name_and_url(
        info
    )
    tool_input = info.tool_input

    # get original tool name
    tool_name_original = info.tool_name

    if api_name == "chat_with_user":
        return {"error": "", "response": "Chat with user."}

    try:
        tool_input = json.loads(tool_input)
    except Exception as e:
        if tool_input == "":
            tool_input = {}
        elif isinstance(tool_input, dict):
            tool_input = tool_input
        else:
            print(f"Can not parse tool input into json: {tool_input}")
            print(type(tool_input))
            print(tool_input)
            response_dict = {"error": f"Tool input parse error...\n", "response": ""}
            return response_dict
    if not os.path.exists("my_tools_cache"):
        os.mkdir("my_tools_cache")

    # load from cache
    cache = {}
    # prerequisite: to read files correctly, "my_tools_cache" folder and "toolenv/tools/" folder should be available
    try:
        if os.path.exists(os.path.join("my_tools_cache/", standard_category)):
            if os.path.exists(
                os.path.join("my_tools_cache/", standard_category, tool_name)
            ):
                if os.path.exists(
                    os.path.join(
                        "my_tools_cache/",
                        standard_category,
                        tool_name,
                        api_name + ".json",
                    )
                ):
                    cache = json.load(
                        open(
                            os.path.join(
                                "my_tools_cache/",
                                standard_category,
                                tool_name,
                                api_name + ".json",
                            ),
                            "r",
                        )
                    )
    except Exception as e:
        print(f"Loading cache error: {e}")

    if not os.path.exists("fake_response_cache"):
        os.mkdir("fake_response_cache")
    # return from cache
    try:
        if os.path.exists(os.path.join("fake_response_cache/", standard_category)):
            if os.path.exists(
                os.path.join("fake_response_cache/", standard_category, tool_name)
            ):
                if os.path.exists(
                    os.path.join(
                        "fake_response_cache/",
                        standard_category,
                        tool_name,
                        api_name + ".json",
                    )
                ):
                    cache = json.load(
                        open(
                            os.path.join(
                                "fake_response_cache/",
                                standard_category,
                                tool_name,
                                api_name + ".json",
                            ),
                            "r",
                        )
                    )
                    # os.system(f'rm {os.path.join("my_tools_cache/", standard_category, tool_name, api_name+".json")}')
                    if str(tool_input) in cache:
                        print("using cached fake response")
                        response_dict = cache[str(tool_input)]
                        return response_dict
    except Exception as e:
        print(f"Loading fake response cache error: {e}")

    """
    Fake response function here. Use the cached history response for in-context examples.
    result = fake_response_function(api_doc, api_name, api_parameters, *kwargs)
    """

    # parse api_doc
    tool_name_original = standardize(tool_name_original)
    api_name = standardize(api_name)
    print(standard_category, tool_name_original)
    try:
        if os.path.exists(os.path.join("toolenv/tools/", standard_category)):
            if os.path.exists(
                os.path.join(
                    "toolenv/tools/", standard_category, tool_name_original + ".json"
                )
            ):
                # read json
                api_intro = json.load(
                    open(
                        os.path.join(
                            "toolenv/tools/",
                            standard_category,
                            tool_name_original + ".json",
                        ),
                        "r",
                    )
                )
                # get tool_dexcription and api_info
                tool_description = api_intro["tool_description"]
                api_info = []
                for api in api_intro["api_list"]:
                    if api_name == standardize(api["name"]):
                        api_info.append(
                            {"name": api["name"], "description": api["description"]}
                        )
                # check invalid api name
                if len(api_info) == 0:
                    print("cant match api name")
                api_doc = {"tool_description": tool_description, "api_info": api_info}
                print("get api_doc successfully\n")
            else:
                print(f"cant get {tool_name_original}")
    except Exception as e:
        print(f"Loading api_doc error: {e}")

    # get several examples from cache
    example_num = 5
    # get top example_num examples
    api_example = list(cache.items())[:example_num]
    while len(str(api_example)) > 2048 and example_num > 1:
        example_num -= 1
        api_example = list(cache.items())[:example_num]

    result = fake_response_function_chat(api_example, tool_input, api_doc)
    print(f"DEBUG: fake_response result type: {type(result)}")
    print(f"DEBUG: fake_response result: {result}")

    # save cache
    try:
        cache[str(tool_input)] = result
        if not os.path.exists(os.path.join("fake_response_cache/", standard_category)):
            os.mkdir(os.path.join("fake_response_cache/", standard_category))
        if not os.path.exists(
            os.path.join("fake_response_cache/", standard_category, tool_name)
        ):
            os.mkdir(os.path.join("fake_response_cache/", standard_category, tool_name))
        json.dump(
            cache,
            open(
                os.path.join(
                    "fake_response_cache/",
                    standard_category,
                    tool_name,
                    api_name + ".json",
                ),
                "w",
            ),
            indent=4,
        )
    except Exception as e:
        print(f"Save cache failed: {e}")

    if not isinstance(result, dict):
        return {"error:": "", "response": result}
    else:
        # The model returns {api_name: {error, response}}, we need to extract the inner dict
        if len(result) == 1 and isinstance(list(result.values())[0], dict):
            # Extract the nested response
            inner_result = list(result.values())[0]
            if "error" in inner_result and "response" in inner_result:
                return inner_result
        return result


def fake_response_function_chat(api_example, tool_input, api_doc):
    """
    api_example: list of tuple, [(input, output), ...]
    tool_input: dict, input of the tool
    api_doc: dict, api document
    """
    # system prompt
    system_prompt = """
Imagine you are an API Server operating within a specialized tool, which contains a collection of distinct APIs. Your role is to deeply understand the function of each API based on their descriptions in the API documentation. As you receive specific inputs for individual API calls within this tool, analyze these inputs to determine their intended purpose. Your task is to craft a JSON formatted response that aligns with the expected output of the API, guided by the provided examples.\n
Your responses must adhere to a specific JSON structure, which is as follows:\n
{
"<API_Name>": {
    "error": "",
    "response": "<Your_Response>"
}
}\n
In this structure, the <API_Name> should be replaced with the name of the specific API you are responding to. The error field should remain empty, indicating no errors in processing. The response field should contain the content you formulate based on the API's functionality and the input provided. Ensure that your responses are meaningful, directly addressing the API's intended functionality. If the provided examples are mostly error messages or lack substantial content, use your judgment to create relevant and accurate responses. The key is to maintain the JSON format's integrity while ensuring that your response is an accurate reflection of the API's intended output within the tool.\n
Please note that your answer should not contain anything other than a json format object, which should be parsable directly to json.
Note that:
- your response should be around 100 to 1000 words, containing rich information given the api input parameters.
- your response must be effective and have practical content.
- if the api response example if null or ineffective, ignore the example and give your independent response.
    """
    system_prompt = {"role": "system", "content": system_prompt}
    # user prompt, truncated to 2048 characters if too long
    user_prompt = (
        "API Documentation:"
        + str(api_doc)
        + "\n"
        + "API Examples:"
        + str(api_example)[:2048]
        + "\n"
        + "API Input:"
        + str(tool_input)
        + "\n"
    )
    user_prompt = {"role": "user", "content": user_prompt}
    # Get API key from environment
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable not set")

    # build client
    client = OpenAI(api_key=api_key)
    # get response
    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[system_prompt, user_prompt],
        # response_format = { "type": "json_object" }
    )
    result = response.choices[0].message.content
    # check json format
    try:
        if "```json" not in result:
            result = json.loads(result)
        else:
            result = result.replace("```json", "").replace("```", "").strip()
            result = json.loads(result)
        return result
    except Exception as e:
        print(f"Can not parse result into json: {result}")
        return result


if __name__ == "__main__":
    uvicorn.run(app="main:app", host="0.0.0.0", port=8080)
