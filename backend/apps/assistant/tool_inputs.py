"""Validate model arguments before executing any known read-only tool."""
import json


def validated_arguments(name, raw, sources):
    try:
        args = json.loads(raw)
    except (TypeError, ValueError) as error:
        raise ValueError('invalid_tool_arguments') from error
    fields = {
        'search_knowledge': {'query', 'queries'},
        'read_evidence': {'source_ref', 'offset', 'budget'},
        'read_context': {'source_ref', 'before', 'after', 'budget'},
        'find_in_source': {'source_ref', 'query', 'budget'},
    }
    if not isinstance(args, dict) or set(args) - fields[name]:
        raise ValueError('invalid_tool_arguments')
    if name != 'search_knowledge' and (not isinstance(args.get('source_ref'), str) or args['source_ref'] not in sources):
        raise ValueError('unknown_source_ref')
    if name in {'search_knowledge', 'find_in_source'}:
        if not isinstance(args.get('query'), str) or not 1 <= len(args['query'].strip()) <= 500:
            raise ValueError('invalid_tool_arguments')
    if 'queries' in args and (not isinstance(args['queries'], list) or len(args['queries']) > 2 or
                              any(not isinstance(q, str) or not 1 <= len(q.strip()) <= 500 for q in args['queries'])):
        raise ValueError('invalid_tool_arguments')
    for key, lower, upper in [('budget', 1, 3000), ('offset', 0, None), ('before', 0, 2), ('after', 0, 2)]:
        if key in args and (type(args[key]) is not int or args[key] < lower or (upper is not None and args[key] > upper)):
            raise ValueError('invalid_tool_arguments')
    return args
