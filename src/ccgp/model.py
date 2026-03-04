from dataclasses import dataclass

#------------------------------数据结构-----------------------------------#
@dataclass
class TenderItem:
    announcement_title: str
    announcement_url: str
    pub_time: str  # ISO
    province: str
    city: str

    project_name: str
    ai_project_title: str
    requirement_brief: str 
    requirement_desc: str

    # 这里区分的比较细
    company_name: str  # 采购单位
    location_text: str  # 采购单位地址
    purchasing_unit_contact_number: str  # 采购单位联系方式
    contact_name: str  # 项目联系人
    contact_phone: str # 项目联系电话

    deadline: str
    budget: str  # 预算金额