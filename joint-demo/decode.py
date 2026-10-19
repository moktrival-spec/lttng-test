"""Decode CTF with Babeltrace 2 Python bindings; preserve the common clock axis."""
import json,sys
import bt2

def native(field):
    if field is None:return None
    name=type(field).__name__
    if hasattr(field,'items'):return {k:native(v) for k,v in field.items()}
    if 'String' in name:return str(field)
    if 'Array' in name or 'Sequence' in name:return [native(x) for x in field]
    try:return int(field)
    except (ValueError,TypeError):return str(field)

count=0
with open(sys.argv[2],'w',encoding='utf-8') as output:
    for message in bt2.TraceCollectionMessageIterator(sys.argv[1]):
        if 'Discarded' in type(message).__name__:
            raise SystemExit('Discarded events/packets in CTF: refuse to present a complete timeline')
        if not isinstance(message,bt2._EventMessageConst):continue
        event=message.event
        data=native(event.payload_field)
        for key,value in list(data.items()):
            if key.endswith('comm') and isinstance(value,list):
                data[key]=bytes(value).split(b'\0',1)[0].decode('utf-8','replace')
        record={'ts_ns':message.default_clock_snapshot.ns_from_origin,'name':event.name,
                'payload':data,'context':native(event.common_context_field),
                'packet':native(event.packet.context_field)}
        output.write(json.dumps(record,ensure_ascii=False)+'\n'); count+=1
print(f'Decoded {count} events; no discarded-event/packet messages')
