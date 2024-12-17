import os
import re
import json
import chardet
import requests


def detect_encoding(file_path):
    """检测文件编码"""
    with open(file_path, 'rb') as f:
        result = chardet.detect(f.read())
    return result['encoding']

def find_rc_files(directory):
    """查找目录下所有.rc文件"""
    rc_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".rc"):
                rc_files.append(os.path.join(root, file))
    return rc_files

def find_translatable_text(rc_file_path, base_dir, translated_dict):
    """查找rc文件中需要汉化的内容，并生成唯一的文件名"""
    encoding = detect_encoding(rc_file_path)
    if encoding.lower() == 'utf-16le' or encoding.lower() == 'utf-16':
        encoding = 'UTF-8'
    
    translatable_text = {}
    try:
        dictValves  = translated_dict.values()
        with open(rc_file_path, 'r', encoding=encoding) as f:
            for line in f:
                # 更新后的、更简化的正则表达式 (假设没有 STRINGTABLE)
                match = re.findall(r'CAPTION\s*"(.*?)"|PUSHBUTTON\s+"(.*?)"|CONTROL\s+"(.*?)"|GROUPBOX\s+"(.+?)"|DEFPUSHBUTTON\s+"(.*?)"|LTEXT\s+"(.*?)"|RTEXT\s+"(.*?)"', line)
                for m in match:
                    # 遍历匹配到的每个元组
                    for text in m:
                        # 如果字符串不为空、是ASCII字符、且不在已翻译字典的键和值中
                        if text and text.isascii() and text not in translated_dict and text not in dictValves:
                            translatable_text[text] = ""


        # 生成唯一的文件名 (相对于 zh_cn 目录)
        # relative_path = os.path.relpath(rc_file_path, base_dir)
        # file_name_base = relative_path.replace(os.sep, '_').replace('.rc', '')
        
        json_file_name = "translate_text.json"
        # JSON 文件将保存在 zh_cn 目录下
        json_file_path = os.path.join(base_dir, json_file_name)
        
        return translatable_text, json_file_path, encoding

    except UnicodeDecodeError:
        print(f"Error decoding file: {rc_file_path} with encoding: {encoding}")
        return {}, None, None

def save_translatable_text_to_json(translatable_text, json_file_path):
    """将需要汉化的文本保存到json文件"""
    #  读取json_file_name = "translate_text.json"
    with open(json_file_path, 'w', encoding='utf-8') as f:
        json.dump(translatable_text, f, ensure_ascii=False, indent=4)

def translate_json(translatable_json):
    """逐个翻译json文件中的key，并将结果保存到value"""
    try:
        # 判断data中是否有值，是否为空
        if not translatable_json:
            print("No translatable text found")
            return

        url = "http://127.0.0.1:1000/v1/chat/completions"
        headers = {
        "Authorization": "Bearer sk-WvMkGkPdrUIXTwRk3014F2C586D74c1a99350165Ec847a69",
        "content-type": "application/json"
        }

        result = {}
        # 如果translatable_json的key 长度大于200, 则分段发送
        if len(translatable_json) > 200:
            for i in range(0, len(translatable_json), 200):
                batch = dict(list(translatable_json.items())[i:i + 200])
                # print(f"发送第 {i // 200 + 1} 批次: {batch}")
                getTranslate(batch, url, headers, result)
        else:
            getTranslate(translatable_json, url, headers, result)

        return result

    except Exception:
        print("翻译失败，请检查翻译内容是否正确")

def getTranslate(translatable_json, url, headers, result):
    payload = {
                    "model": "gemini-2.0-flash-exp",
                    "messages": [
                        {
                        "role": "system",
                        "content": "你是一位计算机软件国际化专家，你的目标是把一个软件中的英文翻译成中文，请翻译时不要带翻译腔，而是要翻译得自然、流畅和地道，保留计算机软件的专业术语。我会发生一串json字符串给你, key是待翻译字段, 你需要把对应的翻译结果填入value中, 如果key不需要翻译, 把key填入value, 最后把key和value按key-->value的格式输出, 比如 hi-->嗨\n, 不要有多余的说明, 直接进行输出"
                        },
                        {
                        "role": "user",
                        "content": json.dumps(translatable_json)
                        }
                    ]
                }
    response = requests.post(url, json=payload, headers=headers)
    res = response.json()
    if res['choices'] and res['choices'][0]['message']["content"]:
        translateContent = res['choices'][0]['message']["content"]
        if "-->" in translateContent:
            # 获取翻译数据
            translateMap = listToMap(translateContent)
            result.update(translateMap)
        else:
            print(f"翻译失败，请检查翻译内容是否正确, response: {res}")
    else:
        print(f"翻译失败，请检查翻译内容是否正确, response: {res}")

def listToMap(content):
    mapvalue = {}
    list = content.split("\n")
    for line in list:
        if len(line.strip()) == 0:
            continue
        sp = line.split("-->")
        if len(sp) < 2:
            continue
        mapvalue[sp[0].strip()] = sp[1].strip()
    return mapvalue

def replace_text_in_rc_file(rc_file_path, translated_dict, encoding):
    """
    根据汉化后的json文件，替换.rc文件中的文本
    """
    try:
        # 预编译正则表达式，匹配所有目标关键词
        pattern = re.compile(
            r'\b(CAPTION|PUSHBUTTON|CONTROL|GROUPBOX|DEFPUSHBUTTON|LTEXT|RTEXT)\s+"(.+?)"',
            re.IGNORECASE
        )

        with open(rc_file_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()

        dictValves  = translated_dict.values()

        def replacer(match):
            control_type, original_text = match.groups()
            # 对于 RTEXT 类型，且内容为 "Static" 的不进行替换
            if control_type.upper() == 'RTEXT' and original_text == 'Static':
                return match.group(0)
            if original_text in dictValves:
                return match.group(0)
            # 如果原文在翻译字典中，则进行替换
            translated_text = translated_dict.get(original_text)
            if translated_text:
                return f'{control_type} "{translated_text}"'
            else:
                return match.group(0)

        # 使用列表推导式和 re.sub 进行替换
        new_lines = [pattern.sub(replacer, line) for line in lines]

        # 将修改后的内容写回文件，保持原编码
        with open(rc_file_path, 'w', encoding='utf-8') as file:
            file.writelines(new_lines)

    except FileNotFoundError:
        print(f"文件未找到: {rc_file_path}")
    except UnicodeDecodeError:
        print(f"解码错误: {rc_file_path} 使用编码: {encoding}")
    except Exception as e:
        print(f"发生错误: {e}")

def main():
    """主函数"""
    # 修改为 zh_cn 目录
    base_dir = os.path.join(os.path.dirname(__file__))
    
    # 确保 zh_cn 目录存在
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)

    # systeminformer 目录
    systeminformer_dir = os.path.dirname(base_dir)
    
    # 已翻译字段
    translated_dict = {}
    with open(base_dir + "/translate_text.json", 'r', encoding='utf-8') as f:
        translated_dict = json.load(f)

    # 所有待翻译的json
    translatable_json = {}
    # 查找所有.rc文件
    rc_files = find_rc_files(systeminformer_dir)

    # 第一次遍历：查找所有需要汉化的文本并保存到json文件
    for rc_file in rc_files:
        translatable_text, json_file_path, encoding = find_translatable_text(rc_file, base_dir, translated_dict)
        translatable_json.update(translatable_text)

        # if json_file_path:
            # save_translatable_text_to_json(translatable_text, json_file_path)

    # 翻译 translatable_json中的key
    translateMap = translate_json(translatable_json)
    if translateMap:
        # 防止有key没有被翻译, 如果有value为空
        translatable_json.update(translateMap)
        translated_dict.update(translatable_json)
        # 保存translatable_json文件
        with open(base_dir + "/translate_text.json", 'w', encoding='utf-8') as f:
            json.dump(translated_dict, f, ensure_ascii=False, indent=4)


    # 遍历：根据翻译后的json文件替换.rc文件中的文本
    for rc_file in rc_files:
        # relative_path = os.path.relpath(rc_file, base_dir)
        # file_name_base = relative_path.replace(os.sep, '_').replace('.rc', '')
        # json_file_name = f"{file_name_base}_en.json"
        # json_file_path = os.path.join(base_dir, json_file_name)

        encoding = detect_encoding(rc_file)
        if encoding.lower() == 'utf-16le' or encoding.lower() == 'utf-16':
            encoding = 'UTF-8'
        
        replace_text_in_rc_file(rc_file, translated_dict, encoding)
        print(f"Replaced text in: {rc_file}")

if __name__ == "__main__":
    main()