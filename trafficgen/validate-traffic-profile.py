#!/usr/bin/python3


import argparse
import json
import traceback

from jsonschema import validate
from pathlib import Path


# define some global variables
class t_global(object):
    args = None


def process_options ():
    parser = argparse.ArgumentParser(description="json-validator provides syntax and schema validation for JSON files");

    parser.add_argument('--json',
                        dest = 'json_file',
                        help = 'The JSON file to analyze.',
                        required = True)

    t_global.args = parser.parse_args();


def main():
    process_options()

    try:
        json_fp = open(t_global.args.json_file, 'r')
        json_contents = json.load(json_fp)
        json_fp.close()

    except:
        print("EXCEPTION: %s" % traceback.format_exc())
        print("ERROR: Could not load a valid JSON file from %s" % (t_global.args.json_file))
        return(1)

    schema_file = Path(__file__).parent / "traffic-profile-schema.json"

    try:
        schema_fp = open(schema_file, 'r')
        schema_contents = json.load(schema_fp)
        schema_fp.close()

    except:
        print("EXCEPTION: %s" % traceback.format_exc())
        print("ERROR: Could not load a valid JSON schema file from %s" % (schema_file))
        return(2)

    try:
        validate(instance=json_contents, schema=schema_contents)

    except:
        print("EXCEPTION: %s" % traceback.format_exc())
        print("ERROR: JSON validation failed for %s using schema %s" % (t_global.args.json_file, schema_file))
        return(3)
            

    return(0)


if __name__ == "__main__":
    exit(main())
