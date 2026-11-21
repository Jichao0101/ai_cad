"""CATIA草图轴系数组封送；整数VARIANT可能被客户端静默忽略。"""


def read(sketch):
    import pythoncom
    import win32com.client
    value=win32com.client.VARIANT(pythoncom.VT_BYREF|pythoncom.VT_ARRAY|pythoncom.VT_VARIANT,[0.0]*9)
    sketch._oleobj_.Invoke(sketch._oleobj_.GetIDsOfNames('GetAbsoluteAxisData'),0,1,0,value)
    return list(value.value)


def set_verified(sketch, frame):
    expected=[float(v) for v in frame]
    sketch.SetAbsoluteAxisData(tuple(expected))
    actual=read(sketch)
    if any(abs(a-b)>1e-7 for a,b in zip(expected,actual)):
        raise ValueError(f'Sketch frame mismatch: expected {expected}, measured {actual}')
