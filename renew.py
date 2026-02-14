import re

def process_m3u_file(input_file, output_file):
    """
    处理M3U文件：删除更新时间消息及其下方的链接，将group-title改为'频道'
    
    Args:
        input_file (str): 输入文件路径
        output_file (str): 输出文件路径
    """
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        # 如果UTF-8失败，尝试其他编码
        with open(input_file, 'r', encoding='gbk') as f:
            content = f.read()
    
    # 按行处理，删除更新时间消息及其下方的链接
    lines = content.split('\n')
    processed_lines = []
    skip_next = False
    
    for i, line in enumerate(lines):
        if skip_next:
            skip_next = False
            continue
            
        # 检查是否为更新时间消息行
        time_patterns = [
            r'#.*更新时间',
            r'#.*\d{4}-\d{2}-\d{2}',
            r'#.*\d{2}:\d{2}:\d{2}',
            r'#.*Update.*time',
            r'#.*Generated.*\d{4}',
            r'#.*最后更新',
            r'#.*Last.*update',
            r'#.*时间.*\d{4}'
        ]
        
        is_time_message = False
        for pattern in time_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                is_time_message = True
                break
        
        if is_time_message:
            # 跳过当前行（时间消息）
            # 检查下一行是否为链接
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                # 如果下一行是URL或者不是#开头的非空行，也跳过
                if (next_line and 
                    not next_line.startswith('#') and 
                    (next_line.startswith('http') or '://' in next_line)):
                    skip_next = True
            continue
        else:
            processed_lines.append(line)
    
    content = '\n'.join(processed_lines)
    
    # 将所有group-title内容改为'频道'
    # 匹配EXTINF行中的group-title属性
    content = re.sub(
        r'group-title="[^"]*"',
        'group-title="频道"',
        content
    )
    
    # 处理没有引号的group-title
    content = re.sub(
        r'group-title=[^\s,]*',
        'group-title="频道"',
        content
    )
    
    # 清理多余的空行
    content = re.sub(r'\n\s*\n\s*\n', '\n\n', content)
    
    # 保存处理后的文件
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"处理完成！已保存到 {output_file}")

def main():
    input_file = "./output/result.m3u"
    output_file = "./output/url.m3u"
    
    try:
        process_m3u_file(input_file, output_file)
        print("M3U文件处理成功！")
        print(f"原文件: {input_file}")
        print(f"新文件: {output_file}")
        
        # 显示处理统计
        with open(input_file, 'r', encoding='utf-8') as f:
            original_lines = len(f.readlines())
        with open(output_file, 'r', encoding='utf-8') as f:
            processed_lines = len(f.readlines())
        
        print(f"原文件行数: {original_lines}")
        print(f"处理后行数: {processed_lines}")
        print(f"删除了 {original_lines - processed_lines} 行")
        
    except FileNotFoundError:
        print(f"错误：找不到文件 {input_file}")
        print("请确保文件存在于当前目录中")
    except Exception as e:
        print(f"处理过程中出现错误: {str(e)}")

if __name__ == "__main__":
    main()