"""國泰海通採集解析單測（離線，用真實頁面片段結構）。"""
from app.collectors.gtht import _parse_fragment

FRAGMENT = """
<ul class="">
  <li class="list-li"><span title="深圳分公司-管培生（2027秋招）" class="con">深圳分公司-管培生（2027秋招）</span></li>
  <li class="list-li" style="display: none;"><span title="深圳分公司" class="con">深圳分公司</span></li>
  <li class="list-li"><span title="本科及以上" class="con">本科及以上</span></li>
  <li class="list-li" style="display: none;"><span title="15" class="con">15</span></li>
  <li class="list-li job-address-col"><span title="深圳" class="con">深圳</span></li>
  <li class="apply-li"><a data-job_id='6001566' class="apply-btn" href="javascript:;">立即申请</a></li>
  <li class="job-description-li"><h4 class="job-description-title">岗位描述</h4>
    <p><p>【工作职责】</p><p>1、参与轮岗交流；</p><p>【任职要求】</p><p>1、本科及以上学历；</p></p>
  </li>
</ul>
"""


def test_parse_fragment():
    jobs = _parse_fragment(FRAGMENT)
    assert len(jobs) == 1
    j = jobs[0]
    assert j["job_id"] == "6001566"
    assert "管培生" in j["title"]
    assert j["education"] == "本科及以上"
    assert j["location"] == "深圳"
    assert "工作职责" in (j["description"] or "")


def test_parse_empty():
    assert _parse_fragment("<div>無內容</div>") == []
