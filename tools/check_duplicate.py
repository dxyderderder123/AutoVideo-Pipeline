#!/usr/bin/env python3
"""
查重工具：检查 input 文件夹中的文章是否已在 finish.md 中记录

使用方法:
    python tools/check_duplicate.py

返回码:
    0 - 无重复文章
    1 - 发现重复文章
"""

import sys
from pathlib import Path


def get_finished_titles(finish_file: Path) -> dict:
    """
    从 finish.md 中读取已完成的标题
    返回: {标题: 日期} 的字典
    """
    finished = {}
    if not finish_file.exists():
        return finished
    
    current_date = ""
    with open(finish_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # 日期行格式: # 250218
            if line.startswith('# '):
                current_date = line[2:].strip()
            else:
                # 标题行
                title = line.strip()
                if title:
                    finished[title] = current_date
    
    return finished


def get_input_titles(input_dir: Path) -> dict:
    """
    从 input 文件夹中读取所有文章的第一行（标题）
    返回: {文件名: 标题} 的字典
    """
    input_titles = {}
    
    if not input_dir.exists():
        print(f"错误: input 文件夹不存在: {input_dir}")
        return input_titles
    
    md_files = sorted(input_dir.glob("*.md"))
    
    if not md_files:
        print(f"警告: input 文件夹中没有 .md 文件")
        return input_titles
    
    for md_file in md_files:
        try:
            with open(md_file, 'r', encoding='utf-8') as f:
                first_line = f.readline().strip()
                # 移除 markdown 标题标记
                title = first_line.lstrip('#').strip()
                input_titles[md_file.name] = title
        except Exception as e:
            print(f"警告: 无法读取文件 {md_file.name}: {e}")
    
    return input_titles


def check_duplicates():
    """主查重逻辑"""
    # 路径配置
    project_root = Path(__file__).resolve().parent.parent
    input_dir = project_root / "workspace" / "input"
    finish_file = project_root / "workspace" / "finish.md"
    
    print("=" * 50)
    print("检查 input 文件夹中的文章重复情况")
    print("=" * 50)
    print()
    
    # 读取数据
    finished_titles = get_finished_titles(finish_file)
    input_titles = get_input_titles(input_dir)
    
    if not input_titles:
        print("input 文件夹为空，无需检查")
        return 0
    
    if not finished_titles:
        print("finish.md 为空或不存在，所有文章都是新的")
        print(f"\n共检查 {len(input_titles)} 篇文章，无重复")
        return 0
    
    # 检查重复
    duplicates = []
    new_articles = []
    
    for filename, title in input_titles.items():
        # 精确匹配标题
        if title in finished_titles:
            duplicates.append({
                'filename': filename,
                'title': title,
                'date': finished_titles[title]
            })
        else:
            new_articles.append({'filename': filename, 'title': title})
    
    # 输出结果
    if duplicates:
        print(f"⚠️  发现 {len(duplicates)} 篇重复文章:")
        print("-" * 50)
        for dup in duplicates:
            print(f"  📄 {dup['filename']}")
            print(f"     标题: \"{dup['title']}\"")
            print(f"     (已在 {dup['date']} 完成)")
            print()
    
    if new_articles:
        print(f"✅ 新文章 ({len(new_articles)} 篇):")
        print("-" * 50)
        for article in new_articles:
            print(f"  📄 {article['filename']}: \"{article['title']}\"")
        print()
    
    print("=" * 50)
    print(f"检查完成: 共 {len(input_titles)} 篇, 重复 {len(duplicates)} 篇, 新文章 {len(new_articles)} 篇")
    print("=" * 50)
    
    if duplicates:
        print("\n❌ 请修改重复文章后再运行全流程")
        return 1
    else:
        print("\n✅ 无重复文章，可以运行全流程")
        return 0


if __name__ == "__main__":
    exit_code = check_duplicates()
    sys.exit(exit_code)
