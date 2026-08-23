"""P4 阶段识别与项目键单测（真实标题样本回归）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from crawl.stage import classify_stage, project_core, project_key, STAGE_LABELS  # noqa: E402


class TestClassifyStage(unittest.TestCase):
    def test_bidding(self):
        cases = [
            "武汉融通中南花园酒店有限责任公司2026-2027年度绿植租摆服务采购项目询比采购公告",
            "南航明珠新疆酒店绿植租摆服务项目询比公告",
            "银联数据绿植租摆服务采购项目竞争性磋商采购公告",
            "杭州创悦盈科技有限责任公司室内绿植租摆养护项目招标公告",
            "深圳市华润资本股权投资有限公司2026年深圳华润金融大厦10楼办公区绿植租摆服务供应商采购公告",
            "招商积余南京公司HW-NYSAB地块绿植租摆服务采购-邀请函",
            "苏州市园林和绿化管理局关于市行政中心大院室内外绿植租摆和公共场所摆花项目招标公告",
            "杭州中心园区物业服务-公开招标公告",
            "分谈分签+中国船舶重工集团有限公司第七一0研究所+武汉研发中心室内绿植租摆服务的询价书",
            "关于医院绿植租赁与养护服务采购公告(绿植租摆 相关在信息中)",
        ]
        for t in cases:
            self.assertEqual(classify_stage(t)[0], "bidding", t)

    def test_change(self):
        self.assertEqual(classify_stage("银联数据绿植租摆服务采购项目更正公告")[0], "change")
        self.assertEqual(classify_stage("南航明珠新疆酒店绿植租摆服务项目延期公告")[0], "change")

    def test_candidate(self):
        cases = [
            "招商商管北部片区南京项目群2026-2027年绿植租摆和绿化养护服务(二次采购)成交候选人公示",
            "2026-2027年南京南部新城城市物业管理有限公司绿植租摆服务中标候选人公示",
            "招商积余南京公司HW-NYSAB地块绿植租摆服务采购成交候选人公示",
        ]
        for t in cases:
            self.assertEqual(classify_stage(t)[0], "candidate", t)

    def test_result(self):
        cases = [
            "2026-2027年南京南部新城城市物业管理有限公司绿植租摆服务中标结果公告",
            "招商商管北部片区苏州项目群2026-2027年绿植租摆和绿化养护服务结果公告",
            "深圳市宝安区住房和建设事务中心绿植租摆服务项目的采购结果公告",
            "华夏银行深圳分行2026-2028年度绿植租摆服务项目采购结果公示",
            "杭州临空建投物业管理有限公司绿植租摆采购及养护采购项目中标结果公示",
            "南京医科大学常州校区物业服务项目（2026年）中标公告(二)(绿植租摆 相关在信息中)",
            "深圳分院工程检测部绿植租赁服务采购结果公示",
        ]
        for t in cases:
            self.assertEqual(classify_stage(t)[0], "result", t)

    def test_terminated(self):
        self.assertEqual(
            classify_stage("招商商管北部片区南京项目群2026-2027年绿植租摆和绿化养护服务开标失败公告")[0],
            "terminated",
        )

    def test_other(self):
        self.assertEqual(classify_stage("绿化租摆和园区除草(查询ID:abc)(绿植租摆 相关在信息中)")[0], "other")
        self.assertEqual(classify_stage("绿植租摆")[0], "other")

    def test_notice_type_fallback(self):
        # 标题无阶段词 → 靠源站编码
        self.assertEqual(classify_stage("招商商管北部片区南京项目群2026-2027年绿植租摆和绿化养护服务", "bidding")[0], "bidding")
        self.assertEqual(classify_stage("某项目", "ZBGS")[0], "result")
        self.assertEqual(classify_stage("某项目", "succeed")[0], "result")
        self.assertEqual(classify_stage("某项目", "free")[0], "other")
        self.assertEqual(classify_stage("某项目", None)[0], "other")


class TestProjectKey(unittest.TestCase):
    def test_same_project_across_stages(self):
        # 同项目：招标 / 候选人 / 结果 / 终止 → 同一个 key
        titles = [
            "招商商管北部片区南京项目群2026-2027年绿植租摆和绿化养护服务",
            "招商商管北部片区南京项目群2026-2027年绿植租摆和绿化养护服务(二次采购)成交候选人公示",
            "招商商管北部片区南京项目群2026-2027年绿植租摆和绿化养护服务(二次采购)结果公告",
            "招商商管北部片区南京项目群2026-2027年绿植租摆和绿化养护服务开标失败公告",
        ]
        keys = {project_key(t, "南京")[0] for t in titles}
        self.assertEqual(len(keys), 2)  # 首次批次 + 二次批次
        k_first = project_key(titles[0], "南京")[0]
        k_second = project_key(titles[1], "南京")[0]
        self.assertNotEqual(k_first, k_second)
        # 二次采购内部：候选人公示与结果公告同一批次
        self.assertEqual(project_key(titles[1], "南京")[0], project_key(titles[2], "南京")[0])

    def test_same_project_cross_source_variants(self):
        k1 = project_key("招商积余南京公司HW-NYSAB地块绿植租摆服务采购-邀请函", "南京")[0]
        k2 = project_key("招商积余南京公司HW-NYS AB地块绿植租摆服务采购成交候选人公示", "南京")[0]
        k3 = project_key("招商积余南京公司HW-NYSAB地块绿植租摆服务采购结果公告", "南京")[0]
        self.assertEqual(k1, k2)
        self.assertEqual(k2, k3)

    def test_different_project_not_merged(self):
        a = project_key("招商商管北部片区南京项目群2026-2027年绿植租摆和绿化养护服务成交候选人公示", "南京")[0]
        b = project_key("招商商管北部片区苏州项目群2026-2027年绿植租摆和绿化养护服务成交候选人公示", "苏州")[0]
        self.assertNotEqual(a, b)
        # 城市参与键：同名项目不同城市不合并
        c = project_key("某公司绿植租摆服务采购结果公告", "南京")[0]
        d = project_key("某公司绿植租摆服务采购结果公告", "武汉")[0]
        self.assertNotEqual(c, d)

    def test_core_strips_noise_and_dates(self):
        core = project_core("南京医科大学常州校区物业服务项目（2026年）中标公告(二)(绿植租摆 相关在信息中)")
        self.assertNotIn("中标公告", core)
        self.assertNotIn("2026", core)
        self.assertIn("南京医科大学常州校区物业", core)


if __name__ == "__main__":
    unittest.main()
