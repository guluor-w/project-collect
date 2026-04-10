import pandas as pd
import re
import os


def plaintext_to_richtext(plaintext):
    # 0. 处理空值和非字符串输入
    if pd.isna(plaintext) or plaintext == "":
        return ""
    
    text = str(plaintext).strip()
    # 统一换行符
    text = text.replace('\r\n', '\n')

    # 1. 优先处理原有自定义格式：【内容】 -> 带样式的 Span
    def replace_custom_style(match):
        content = match.group(1)
        return f'<span style="color: rgb(0, 0, 0); font-size: 15px;"><strong>{content}</strong></span>'
    
    text = re.sub(r'\【(.*?)\】', replace_custom_style, text)

    # 2. 增加 Markdown 风格加粗支持：**内容** -> <strong>内容</strong>
    text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)

    # 3. 分段处理（按双换行符分割段落）
    paragraphs = text.split('\n\n')
    new_paragraphs = []

    for p in paragraphs:
        lines = [line.strip() for line in p.split('\n') if line.strip()]
        if not lines:
            continue
        
        first_line = lines[0]
        
        # 检测是否为无序列表 (以 - 或 * 开头)
        if first_line.startswith('- ') or first_line.startswith('* '):
            list_items = []
            for line in lines:
                # 移除列表标记
                content = re.sub(r'^[-*]\s+', '', line)
                list_items.append(f'<li>{content}</li>')
            new_paragraphs.append(f'<ul>{"".join(list_items)}</ul>')
            
        # 检测是否为有序列表 (以数字. 开头)
        elif re.match(r'^\d+\.', first_line):
            list_items = []
            for line in lines:
                # 移除数字标记
                content = re.sub(r'^\d+\.\s+', '', line)
                list_items.append(f'<li>{content}</li>')
            new_paragraphs.append(f'<ol>{"".join(list_items)}</ol>')
            
        else:
            # 普通段落：每一行都作为独立段落处理
            for line in lines:
                new_paragraphs.append(f'<p>{line}</p>')

    return ''.join(new_paragraphs)


if __name__ == "__main__":
    # 读取 CSV 文件
    file_name = "cleaned_requirements"
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, f'{file_name}.csv')

    try:
        # 尝试作为 Excel 文件读取（即使扩展名是 .csv），因为文件头显示它是 ZIP 格式（Excel .xlsx）
        try:
            df = pd.read_excel(file_path, engine='openpyxl')
        except Exception:
            # 如果不是 Excel，尝试作为 CSV 读取
            try:
                df = pd.read_csv(file_path, encoding='utf-8')
            except UnicodeDecodeError:
                df = pd.read_csv(file_path, encoding='gb18030')

        # 处理“资源描述”列
        if '资源描述' in df.columns:
            df['资源描述'] = df['资源描述'].apply(plaintext_to_richtext)
            # 保存处理后的文件
            output_file = os.path.join(script_dir, f'{file_name}_处理后.csv')
            df.to_csv(output_file, index=False, encoding='utf-8-sig')
            print(f'处理完成，结果已保存到 {output_file}')
        else:
            print('错误：文件中未找到“资源描述”列')

    except FileNotFoundError:
        print(f'错误：未找到文件 {file_path}')
    except KeyError:
        print('错误：文件中未找到“资源描述”列')
    except Exception as e:
        print(f'发生未知错误：{e}')
