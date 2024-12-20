import re
import os
import json
from itertools import islice
import requests

def find_rc_files(directory):
    """查找目录下所有.c文件"""
    rc_files = []
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".c"):
                rc_files.append(os.path.join(root, file))
    return rc_files

def find_translatable_strings(c_file_path, translated_dict, translated_files):
    """
    查找C/C++文件中需要翻译的字符串, 针对 PhCreateEMenuItem
    """
    translatable_text = set()
    try:
        dictValves  = translated_dict.values()
        regex = re.compile(r'L"([^"]+)"')
        with open(c_file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line_num, line in enumerate(f, start=1):  # 添加行号
                match = regex.search(line)
                if match:
                    translated_files.add(c_file_path)
                    text = match.group(1)
                    if text and text not in translated_dict and text not in dictValves:
                       translatable_text.add(text)
    except FileNotFoundError:
        print(f"错误: 文件未找到 {c_file_path}")
    except Exception as e:
        print(f"读取文件时发生错误: {e}， 位置: {line_num}, line: {line.strip()}")
    return translatable_text


def replace_strings(c_file_path, translated_dict):
    """
    替换C文件中的字符串
    """
    try:
        with open(c_file_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()

        dictValves  = translated_dict.values()
        # 使用列表推导式和 re.sub 进行替换
        regex = re.compile(r'PhCreateEMenuItem\s*\([^,]+,\s*[^,]+,[^\"]*\"([^\"]+)\"')
        new_lines = []
        for line in lines:
            match = regex.search(line)
            if match:
                text = match.group(1)
                # 已翻译过的字段
                if text in dictValves:
                    continue
                line = line.replace(f'"{text}"', f'"{translated_dict.get(text)}"')
            new_lines.append(line)

        # 将修改后的内容写回文件，保持原编码
        with open(c_file_path, 'w', encoding='utf-8') as file:
            file.writelines(new_lines)

    except Exception as e:
         print(f"发生错误: {e}")


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
        if len(translatable_json.keys()) > 200:
             for i in range(0, len(translatable_json), 200):
                batch = dict(islice(translatable_json.items(), i, i + 200))
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
    response.raise_for_status()  # 检查请求是否成功
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
        if len(sp) != 2:
            continue
        mapvalue[sp[0].strip()] = sp[1].strip()
    return mapvalue

def getUntranslatedKeys(c_files, translated_dict, translated_files):
    """获取c文件中被""包裹的字段, 但没有被翻译过的字段"""
    untranslated_keys = set()
     # 提取可翻译字符串
    for c_file in c_files:
        translatable_text = find_translatable_strings(c_file, translated_dict, translated_files)
        untranslated_keys.update(translatable_text)
    return untranslated_keys

def main():

    # 修改为当前文件目录
    base_dir = os.path.dirname(__file__)
    
    # 确保目录存在
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)

    # systeminformer 目录 (未使用，可以删除或者根据实际需求修改)
    systeminformer_dir = os.path.dirname(base_dir)

    # 查找所有.c文件
    c_files = find_rc_files(systeminformer_dir)

    # 已翻译字段
    translated_dict = {}
    translation_file_path = os.path.join(base_dir, "translate_text.json")

    untranslation_file_path = base_dir + "/untranslate2.txt"

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
    translatable_json = {}
    # 获取translated_dict中value为空的key, 放入translatable_json
    for key, value in translated_dict.items():
        if not value:
            translatable_json[key] = ""

    # 翻译过的文件
    translated_files = set()

    # 单独获取所有待翻译的字段
    untranslation_keys = getUntranslatedKeys(c_files,translated_dict, translated_files)
    if untranslation_keys:
        # 写入 untranslate_text.txt
       with open(untranslation_file_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(untranslation_keys) + "\n")

    # 翻译 translatable_json中的key
    # translateMap = translate_json(translatable_json)
    # if translateMap:
    #     # 防止有key没有被翻译, translateMap中没有key
    #     translatable_json.update(translateMap)
    #     translated_dict.update(translatable_json)
    #     # 保存translatable_json文件
    #     with open(base_dir + "/translate_text.json", 'w', encoding='utf-8') as f:
    #         json.dump(translated_dict, f, ensure_ascii=False, indent=4)

    # # 替换 C 文件中的字符串
    # for c_file in translated_files:
    #     replace_strings(c_file, translated_dict)

if __name__ == "__main__":
    main()
    