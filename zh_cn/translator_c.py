import re
import os
import json
from itertools import islice
import requests

fix_regex = re.compile(r'L"([^"]+)"')

def contains_chinese_regex(text: str) -> bool:
    """
    使用正则表达式检查文本中是否包含中文字符。

    Args:
        text: 要检查的文本。

    Returns:
        如果文本中包含中文字符，则返回 True，否则返回 False。
    """
    pattern = re.compile(r'[\u4e00-\u9fff]')
    return bool(pattern.search(text))

def is_untranslatable_file(text, translated_dict):
    """ 如果text不包含中文, 属于术语不需要翻译 """
    return text and not contains_chinese_regex(text) and text != translated_dict.get(text)

def find_rc_files(directory, suffix=".c"):
    """查找目录下所有.rc文件"""
    rc_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(suffix):
                rc_files.append(os.path.join(root, file))
    return rc_files

def find_translatable_strings_by_line(c_file_path, translated_dict, translated_files, regex):
    """
    查找C/C++文件中需要翻译的字符串, 针对 PhCreateEMenuItem
    """
    translatable_text = {}
    try:
        with open(c_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line_num, line in enumerate(f, start=1):  # 添加行号
                # 匹配 PhCreateEMenuItem 函数中的 L"..." 字符串
                match = regex.search(line)
                if match:
                    translated_files.add(c_file_path)
                    text = match.group(1)
                    if is_untranslatable_file(text, translated_dict):
                       translatable_text[text] = ""
    except FileNotFoundError:
        print(f"错误: 文件未找到 {c_file_path}")
    except Exception as e:
        print(f"读取文件时发生错误: {e}， 位置: {line_num}, line: {line.strip()}")
    return translatable_text

def find_translatable_strings_by_line_by_onefile(c_file_path, translated_dict, translated_files, regex):
    """
    查找C/C++文件中需要翻译的字符串
    """
    translatable_text = {}
    try:
        with open(c_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
            match_contents = re.finditer(regex, content)
            if any(match_contents):
                translated_files.add(c_file_path)
                for match in match_contents:
                    text = match.group(1)
                    if is_untranslatable_file(text, translated_dict):
                        translatable_text[text] = ""
   
    except Exception as e:
        print(f"读取文件时发生错误: {e}")
    return translatable_text

def find_translatable_strings_by_onefile_multi_regex(c_file_path, translated_dict, msgRegexList, translated_file_regexs):
    """ 根据多段正则匹配文件里 """
    untranslatable_text = {}
    with open(c_file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    for regex in msgRegexList:
        for match in regex.finditer(content):
            # 获取整个匹配的字符串
            item = match.group(0)  
            # 匹配 L"..." 字符串
            matches = re.findall(fix_regex, item)
            if any(matches):
                # 记录要修改的文件和正则表达式
                translated_file_regexs.setdefault(c_file_path, set()).add(regex)
            for text in matches:
                # 未翻译过的字段
                if is_untranslatable_file(text, translated_dict):
                    untranslatable_text[text] = ""
    return untranslatable_text

def replace_strings(c_file_path, translated_dict, regex):
    """
    替换C文件中的字符串
    """
    try:
        with open(c_file_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()

        # 使用列表推导式和 re.sub 进行替换
        new_lines = []
        for line in lines:
            match = regex.search(line)
            if match:
                text = match.group(1)
                # 未翻译过的字段
                if is_untranslatable_file(text, translated_dict):
                    line = line.replace(f'"{text}"', f'"{translated_dict.get(text)}"')
            new_lines.append(line)

        # 将修改后的内容写回文件，保持原编码
        with open(c_file_path, 'w', encoding='utf-8') as file:
            file.writelines(new_lines)

    except Exception as e:
         print(f"发生错误: {e}")

def replace_strings_by_onefile_multi_regex(c_file, regexs, translated_dict):
    is_update = False
    replacements = []
    with open(c_file, 'r+', encoding='utf-8') as f:
        content = f.read()
        for regex in regexs:
            # 匹配PhShowMessage等函数
            for match in regex.finditer(content):
                # 获取整个匹配的字符串
                item = match.group(0)
                translate_text = item
                # 匹配 L"..." 字符串
                matches = re.findall(fix_regex, item)
                for text in matches:
                    value = translated_dict.get(text)
                    if value and value != text:
                        translate_text = translate_text.replace(f'L"{text}"', f'L"{value}"')
                        # print(translate_text)
                if matches and translate_text != item:
                    # content = content.replace(item, translate_text)
                    replacements.append((match.start(), match.end(), translate_text))
                    is_update = True
        if is_update:
            # 写入 content
            new_content = ""
            last_end = 0
            
            for start, end, replacement_text in replacements:
                new_content += content[last_end:start] + replacement_text
                last_end = end
            new_content += content[last_end:]

            f.seek(0)
            f.write(new_content)
            f.truncate()

def translate_json(untranslatable_json):
    """逐个翻译json文件中的key，并将结果保存到value"""
    try:
        # 判断data中是否有值，是否为空
        if not untranslatable_json:
            # print("No translatable text found")
            return

        url = "http://127.0.0.1:1000/v1/chat/completions"
        headers = {
        "Authorization": "Bearer sk-WvMkGkPdrUIXTwRk3014F2C586D74c1a99350165Ec847a69",
        "content-type": "application/json"
        }

        result = {}
        # 如果untranslatable_json的key 长度大于200, 则分段发送
        if len(untranslatable_json.keys()) > 200:
             for i in range(0, len(untranslatable_json), 200):
                batch = dict(islice(untranslatable_json.items(), i, i + 200))
                getTranslate(batch, url, headers, result)
        else:
            getTranslate(untranslatable_json, url, headers, result)

        return result

    except Exception:
        print("翻译失败，请检查翻译内容是否正确")


def getTranslate(untranslatable_json, url, headers, result):
    payload = {
                    # "model": "gemini-2.0-flash-exp",
                    "model": "gpt-4o",
                    "messages": [
                        {
                    #     "role": "system",
                    #     "content": "你是一位计算机软件国际化专家，你的目标是把一个软件中的英文翻译成中文，请翻译时不要带翻译腔，而是要翻译得自然、流畅和地道，保留计算机软件的专业术语。"
                    #     },
                    #     {
                    #     "role": "user",
                    #     "content": "你是一位计算机软件国际化专家，你的目标是把一个软件中的英文翻译成中文，请翻译时不要带翻译腔，而是要翻译得自然、流畅和地道，保留计算机软件的专业术语。我会发生字符串给你, 你需要把字符串按换行符分割，每一行都是需要独立翻译的句子, 最后把每一行原文和翻译结果按key-->value的格式输出, 比如 hi-->嗨\n, 不要有多余的说明, 直接进行输出, 下面是待翻译的字符串\n```\n" + "\n".join(untranslatable_json.keys())

                        "role": "system",
                        "content": "你是一位计算机软件国际化专家，你的目标是把一个软件中的英文翻译成中文，请翻译时不要带翻译腔，而是要翻译得自然、流畅和地道，保留计算机软件的专业术语。"
                        },
                        {
                        "role": "user",
                        "content": "你是一位计算机软件国际化专家，你的目标是把一个软件中的英文翻译成中文，请翻译时不要带翻译腔，而是要翻译得自然、流畅和地道，保留计算机软件的专业术语。我会发生一串json字符串给你, key是待翻译字段, 你需要把对应的翻译结果填入value中, 如果key不需要翻译, 把key填入value, 最后把key和value按key-->value的格式输出, 比如 hi-->嗨\n, 不要有多余的说明, 直接进行输出, 下面是待翻译的内容\n```\n{" + json.dumps(untranslatable_json)
                        }
                    ]
                    
                }
    
    content = ""
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()  # 检查请求是否成功
        res = response.json()

        content = res.get('choices', [{}])[0].get('message', {}).get('content')
        if not content:
            print(f"翻译内容为空, response: {res}")
        if "-->" in content:
            # 获取翻译数据
            translateMap = listToMap(content)
            result.update(translateMap)
        else:
            if match := re.search(r'\{.*\}', content, re.DOTALL):
                translateMap = json.loads(match.group(0))
                result.update(translateMap)
            else: 
                print(f"翻译失败，请检查翻译内容是否正确, content: {content} , params: {untranslatable_json}")
    except requests.exceptions.RequestException as e:
        print(f"请求失败: {e}")
    except json.JSONDecodeError as e:
        print(f"JSON解析错误: {e}")
        print(f"翻译失败，请检查翻译内容是否正确, content: {content} , params: {untranslatable_json}")
    except Exception as e:
        print(f"未知错误: {e}")
        print(f"翻译失败，请检查翻译内容是否正确, content: {content} , params: {untranslatable_json}")


def listToMap(content):
    mapvalue = {}
    list = content.split("\n")
    for line in list:
        if len(line.strip()) == 0:
            continue
        sp = line.split("-->")
        if len(sp) != 2:
            continue
        mapvalue[sp[0]] = sp[1]
    return mapvalue

def translata_by_fixComponent(c_files, base_dir, systeminformer_dir, untranslatable_json, translated_dict, regex):
    """通过后缀名判断文件类型，调用相应的翻译函数"""
    
    # 翻译过的文件
    translated_files = set()
    # 提取可翻译字符串
    for c_file in c_files:
        translatable_text = find_translatable_strings_by_line(c_file, translated_dict, translated_files, regex)
        untranslatable_json.update(translatable_text)

     # 翻译 untranslatable_json中的key
    translateMap = translate_json(untranslatable_json)
    if translateMap:
        # 防止有key没有被翻译, translateMap中没有key
        untranslatable_json.update(translateMap)
        translated_dict.update(untranslatable_json)
        # 保存untranslatable_json到translated_dict
        with open(base_dir + "/translate_text.json", 'w', encoding='utf-8') as f:
            json.dump(translated_dict, f, ensure_ascii=False, indent=4)

    # 替换 C 文件中的字符串
    for c_file in translated_files:
        replace_strings(c_file, translated_dict, regex)

def getFixRegex(Prefix, paramNum):
        fixTxt = 'L"([^"]+)"'
        """Prefix表示哪个函数, paramNum表示汉化字段前面的参数个数"""
        text = ''
        for i in range(paramNum):
            text += '[^,]+,\s*'
        return re.compile(Prefix + '\s*\(' + text + fixTxt)
    
def getFixRegex2(Prefix, paramNum, paramNum2 = 1, endStr = ""):
    """Prefix表示哪个函数, paramNum表示汉化字段前面的参数个数"""
    text = ''
    for i in range(paramNum):
        text += '[^,]+,\s*'
    param_l = ['L"([^"]+)"' for _ in range(paramNum2)]
    text += ",\s*".join(param_l)

    # for i in range(paramNum2):
    #     text += 'L"([^"]+)",\s*'
    # # 移除最后的,\s*
    # text = text[:-4]
    return re.compile(Prefix + '\s*\(' + text + endStr, re.DOTALL)

def translata_by_ShowMessage(c_files, base_dir, untranslatable_json, translated_dict, msgRegexStrs):
    """先从第一段正则找出匹配项, 再从第二段正则找出翻译项, 最后替换"""

    translated_file_regexs = {}

    msgRegexList = [re.compile(r, re.DOTALL) for r in msgRegexStrs] 
    
    for c_file in c_files:
        untranslatable_text = find_translatable_strings_by_onefile_multi_regex(c_file, translated_dict, msgRegexList, translated_file_regexs)
        untranslatable_json.update(untranslatable_text)
    # 翻译
    translateMap = translate_json(untranslatable_json)
    if translateMap:
        # 防止有key没有被翻译, translateMap中没有key
        untranslatable_json.update(translateMap)
        translated_dict.update(untranslatable_json)
        # 保存untranslatable_json到translated_dict
        with open(base_dir + "/translate_text.json", 'w', encoding='utf-8') as f:
            json.dump(translated_dict, f, ensure_ascii=False, indent=4)

    for c_file, regexs in translated_file_regexs.items():
        replace_strings_by_onefile_multi_regex(c_file, regexs, translated_dict)


def main():

    # 修改为当前文件目录
    base_dir = os.path.dirname(__file__)
    
    # 确保目录存在
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)

    # systeminformer 目录 (未使用，可以删除或者根据实际需求修改)
    systeminformer_dir = os.path.dirname(base_dir)

    # 已翻译字段
    translated_dict = {}
    translation_file_path = os.path.join(base_dir, "translate_text.json")

    if os.path.exists(translation_file_path):
      try:
        with open(translation_file_path, 'r', encoding='utf-8') as f:
          translated_dict = json.load(f)
      except Exception as e:
          print(f"读取翻译文件失败: {e}, 将会使用空字典")
          translated_dict = {}
    else:
        print("翻译文件不存在, 将会使用空字典")

    # 所有待翻译的json
    untranslatable_json = {}
    # 获取translated_dict中没翻译的key, 放入untranslatable_json
    for key, value in translated_dict.items():
        if not value:
            untranslatable_json[key] = ""
        if "\\" in key:
            # 比较key和value中的\ 数量是否相同
            if len(key.split("\\")) != len(value.split("\\")):
                print(f"\ 数量不相同: {key} -> {value}")

    # 查找所有.c文件
    c_files = find_rc_files(systeminformer_dir, ".c")

    
    
    # regex = getFixRegex('PhCreateEMenuItem', 2)
    # regex = re.compile(r'PhCreateEMenuItem\s*\([^,]+,\s*[^,]+,[^\"]*\"([^\"]+)\"')
    # translata_by_fixComponent(c_files, base_dir, systeminformer_dir, untranslatable_json, translated_dict, regex)

    # 查找_In_ PWSTR Text 参数的函数


    # regex = getFixRegex('PhAddListViewGroupItem', 3)
    # regex = getFixRegex('PhAddListViewColumn', 6)
    # regex = getFixRegex('PhAddListViewItem', 2)

    # regex = getFixRegex('PhSetListViewSubItem', 3)

    # regex = getFixRegex('PhAddListViewGroup', 2)

    # regex = getFixRegex('PhAddTreeNewColumn', 3)
    # regex = getFixRegex('PhAddTreeNewColumnEx', 3)
    # regex = getFixRegex('PhAddTreeNewColumnEx2', 3)
    regex = getFixRegex('PhPluginCreateEMenuItem', 3)
    # translata_by_fixComponent(c_files, base_dir, systeminformer_dir, untranslatable_json, translated_dict, regex)
    # show相关函数翻译
    msgRegexStrs = ['Ph[p]?Show\w+\((.*?)\)']
    # 设备函数翻译
    # msgRegexStrs = ['const DEVICE_PROPERTY_TABLE_ENTRY DeviceItemPropertyTable\[\] =\s*\{(.*?)\};']
    # c_files = ['F:\systeminformer_zh\systeminformer_my\plugins\HardwareDevices\devicetree.c']
    # 防火墙翻译
    # msgRegexStrs = ['static[^\[]+\[\] =\s*\{(.*?)\};']
    # c_files = ['F:/systeminformer_zh/systeminformer_my/plugins/ExtendedServices/trigger.c']
    # 描述文本翻译
    # msgRegexStrs = ['column\.Text =(.*?);']
    # msgRegexStrs = ['info->DisplayName =(.*?);', 'info->Description =(.*?);']
    # msgRegexStrs = ['const static COLUMN_INFO columns\[\] =\s*\{(.*?)\};']
    # msgRegexStrs = ['static PH_KEY_VALUE_PAIR GraphTypePairs\[\] =\s*\{(.*?)\};', 'static PWSTR GraphTypeStrings\[\] =\s*\{(.*?)\}', 'static PWSTR CustomizeTextOptionsStrings\[\] =\s*\{(.*?)\}', 'static PWSTR CustomizeSearchDisplayStrings\[\] =\s*\{(.*?)\}']
    msgRegexStrs = ['ToolbarRegisterGraph\((.*?)\);', 'RegisterTrayIcon\((.*?)\);']
    translata_by_ShowMessage(c_files, base_dir, untranslatable_json, translated_dict, msgRegexStrs)

if __name__ == "__main__":
    main()
    