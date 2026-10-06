"""Reproducible backend workflow in temporary SQLite; no live database reset."""
import csv
import io
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from axdesk import Desk, DeskError


def run():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as temp:
        desk = Desk(Path(temp)/'desk.sqlite3', root/'data')
        initial = desk.state()
        stages = []
        def blocked(stage):
            try:
                desk.export()
                raise AssertionError('Export unexpectedly allowed')
            except DeskError as e:
                assert e.status == 409
                stages.append({'stage':stage,'export_status':409,'code':e.code})
        blocked('unresolved')
        for edit in [
            {'id':'S004','excluded':True,'reason':'Synthetic duplicate: original S001 retained'},
            {'id':'S003','value':'9500','reason':'Synthetic source confirmation'},
            {'id':'S005','value':'0.7','unit':'MWh','reason':'Synthetic source says0.7MWh, not700Wh'},
            {'id':'S006','value':'10','period':'2026-09','reason':'Synthetic source confirmation'}
        ]:
            desk.repair(edit)
        clean = desk.state()
        assert clean['summary']['normalized_kwh'] == '46200.0'
        blocked('corrected-unreviewed')
        desk.review({'reviewer':'Demo reviewer','note':'Synthetic source checks only','digests':clean['digests']})
        exported = list(csv.DictReader(io.StringIO(desk.export())))
        assert len(exported) == 5
        stages.append({'stage':'reviewed','export_status':200,'rows':len(exported),'normalized_kwh':'46200.0'})
        desk.repair({'id':'S001','value':'12001'})
        assert desk.state()['review']['status'] == 'stale'
        blocked('edited-after-review')
        result = {'scope':'synthetic deterministic workflow; not business improvement metrics',
                  'initial':initial['summary'],'corrected':clean['summary'],'stages':stages}
        print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    run()
