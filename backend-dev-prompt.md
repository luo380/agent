# Backend Dev Prompt

每次修改后端代码前，先看这份文件。

## 必须遵守

1. 先最小化改动
- 先定位具体函数、路由、schema 或 service，再做局部修改。
- 不要为了改一个文案或 prompt，顺手大面积改文件其它部分。

2. 中文必须防乱码
- 涉及中文注释、中文 prompt、中文返回文案时，文件必须保持 UTF-8。
- 不要用容易破坏中文和换行的批量替换方式。
- 改完后必须验证文件里的真实字符是否正常，不能只看终端显示。
- 不再用这种容易污染编码的 PowerShell 文本替换方式改中文
- 优先用更安全的补丁方式改文件
- 改到中文时先确认文件实际编码，再落改
- 不确定编码是否正常时，优先用脚本按 UTF-8 读取并验证，不要只依赖 PowerShell 直接输出。
- Chinese text rule: all Chinese content must remain valid UTF-8 text, and must never be changed into mojibake or garbled replacement text.
