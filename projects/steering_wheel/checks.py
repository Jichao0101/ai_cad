"""验证固定检查规则并逐项判定；规则来源不等同于DS适用性批准。"""
import math


def rules_for(step):
    """旧单项check与新checks互斥，统一为检查列表供执行器使用。"""
    if 'check' in step and 'checks' in step:
        raise ValueError('Use check or checks, not both')
    if 'checks' in step:
        rules=step['checks']
        if not isinstance(rules,list) or not rules:
            raise ValueError('checks must be a nonempty list')
    elif 'check' in step:
        rules=[{'id':'legacy',**step['check']}]
    else:return []
    seen=set()
    for rule in rules:
        for field in ('id','measurement','source'):
            if not isinstance(rule.get(field),str) or not rule[field].strip():
                raise ValueError('Check requires '+field)
        if rule['id'] in seen:raise ValueError('Duplicate check ID: '+rule['id'])
        seen.add(rule['id'])
        if 'checks' in step:
            for field in ('version','unit'):
                if not isinstance(rule.get(field),str) or not rule[field].strip():
                    raise ValueError('Check requires '+field)
        bounds=[name for name in ('minimum','maximum') if name in rule]
        if not bounds:raise ValueError('Check requires a minimum or maximum')
        for name in bounds:
            value=rule[name]
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
                raise ValueError('Check requires finite '+name)
        if len(bounds)==2 and rule['minimum']>rule['maximum']:
            raise ValueError('Check minimum exceeds maximum')
    return rules


def evaluate(step,measured):
    """缺项或非有限测量属于技术异常，不可作为设计改参依据。"""
    results=[]
    for rule in rules_for(step):
        actual=measured.get(rule['measurement'])
        if isinstance(actual,bool) or not isinstance(actual,(int,float)) or not math.isfinite(actual):
            raise ValueError('Missing or invalid measurement: '+rule['measurement'])
        passed=('minimum' not in rule or actual>=rule['minimum']) and ('maximum' not in rule or actual<=rule['maximum'])
        results.append({**rule,'actual':actual,'passed':passed})
    return results
