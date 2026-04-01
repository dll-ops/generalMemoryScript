# 通用记忆脚本（generalMemoryScript）

这是一个基于 **A-B 对照** 的记忆训练工具。你可以导入自己的词典表格（相邻两列为一组 A-B），并在终端中进行多种记忆训练。

**最新版脚本：`dtm.py`**（即 `dict_trainer_mac.py`）。

## 功能概览

- **记忆卡**：双面浏览
- **选择题**：给 A 选 B
- **填空题**：给 A 填 B（支持同义项）
- **判断题**：Q=正确 / E=错误
- **错题本**：权重强化练习（同一词典对应同一错题本）

## 支持文件格式

- **.xlsx / .xlsm**（需要 `openpyxl`）
- **.csv / .tsv / .txt**
- **.json**（形如 `[[A, B], ...]` 或 `[{"A":..., "B":...}, ...]`）

## 使用方式（dtm.py）

```bash
python dict_trainer_mac.py /path/to/dict.xlsx
```

可选参数：

- `--col`：指定起始列（1-based），B 为下一列
- `--sep`：CSV 分隔符（如 Tab 用 `--sep $'\t'`）

示例：

```bash
python dict_trainer_mac.py /path/to/dict.xlsx --col 3
python dict_trainer_mac.py /path/to/dict.csv --sep $'\t'
```

## 依赖

- 读取 Excel：`pip install openpyxl`
- Windows 终端运行（如需）：`pip install windows-curses`

## 备注

- **请以 `dict_trainer_mac.py` 作为最新版维护与使用入口。**
- 错题本会保存在同目录下：`wrong_book_<id>.json`。
