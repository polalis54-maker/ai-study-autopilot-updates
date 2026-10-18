"""Structured batched SAA-C03 generation with partial-result salvage.

Only creates proposals; Gemini review happens separately in update_watchdog.py.
"""
from __future__ import annotations
import json
import urllib.error
import urllib.request

import autopilot as a

FIELDS={
    'id':{'type':'string'}, 'exam':{'type':'string'},
    'domain':{'type':'string'}, 'topic':{'type':'string'},
    'type':{'type':'string'}, 'question':{'type':'string'},
    'choices':{'type':'array','items':{'type':'string'}},
    'correct':{'type':'array','items':{'type':'string'}},
    'explanation':{'type':'string'}, 'difficulty':{'type':'string'}
}
SCHEMA={
    'type':'object','additionalProperties':False,'required':['questions'],
    'properties':{'questions':{
        'type':'array','items':{
            'type':'object','additionalProperties':False,
            'required':list(FIELDS),'properties':FIELDS
        }
    }}
}


def structured_batch_call(client, prompt, payload):
    """Use API-enforced schema instead of fragile JSON-only prompting."""
    if client.calls>=client.limit:
        raise RuntimeError('API request cap reached')
    client.calls+=1
    request={
        'model':a.OPENAI_MODEL,
        'instructions':prompt + (
            '\nChoices must be a JSON ARRAY of 4 strings for single or 5 strings'
            ' for multiple, in A/B/C/D(/E) order. Follow every spec exactly.'
        ),
        'input':json.dumps(payload,ensure_ascii=False),
        'store':False, 'max_output_tokens':9500,
        'reasoning':{'effort':'low'},
        'text':{'format':{
            'type':'json_schema','name':'saa_batch',
            'strict':True,'schema':SCHEMA
        }}
    }
    req=urllib.request.Request(
        'https://api.openai.com/v1/responses',
        data=json.dumps(request,ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type':'application/json',
                 'Authorization':'Bearer '+client.keys['openai']},
        method='POST'
    )
    try:
        with urllib.request.urlopen(req,timeout=180) as response:
            output=json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'OpenAI structured response HTTP {exc.code}') from None
    except (TimeoutError,urllib.error.URLError):
        raise RuntimeError('OpenAI network error / timeout') from None
    if output.get('status')=='incomplete':
        reason=(output.get('incomplete_details') or {}).get('reason','unknown')
        raise ValueError('OpenAI response truncated: '+str(reason))
    if output.get('status')!='completed':
        raise ValueError('OpenAI response not completed')
    texts=[item.get('text','') for block in output.get('output',[])
           for item in block.get('content',[])
           if item.get('type')=='output_text']
    if not texts:raise ValueError('No OpenAI structured output')
    return a.parse_reply(''.join(texts))


def salvage_batch(api,specs,prompt):
    """Return individual valid questions even when other questions are invalid."""
    by_id={s['id']:s for s in specs}
    response=api.call('openai',prompt,{'specs':specs})
    questions=response.get('questions',[])
    if not isinstance(questions,list):raise ValueError('questions must be array')
    found={}
    for q in questions:
        if not isinstance(q,dict) or q.get('id') not in by_id or q['id'] in found:
            continue
        try:
            a.validate(q,strict=True)
            spec=by_id[q['id']]
            if (q['exam']!='SAA-C03' or q['type']!=spec['type']
                or q['domain']!=spec['domain']
                or q['difficulty']!=spec['difficulty']):
                continue
            if q['type']=='multiple' and not any(t in q['question']
                 for t in ('2つ','２つ','二つ','2 つ')):
                continue
            q['source']={'kind':'original',
                         'label':'AI Study Auto-generated / AI review pending'}
            q['review_status']='ai_review_pending'
            q['language']='ja'
            found[q['id']]=q
        except (ValueError,KeyError,TypeError):
            continue
    return [found[s['id']] for s in specs if s['id'] in found]
