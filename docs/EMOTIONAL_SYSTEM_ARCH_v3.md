# 德克萨斯全息情绪系统 (Texas Holographic Mood System) v3.9

> **核心愿景**：从 v2.0 的“线性阈值触发”进化为 **“多维共鸣场 (Resonance Fields)”** 与 **“立体情绪矩阵 (Holographic Mood Matrix)”**。
>
> 目标是实现 **“千人千面”的欲望表现**。同样的欲望值，在不同的情绪底色（PAD）、生理状态和时间维度下，演绎出截然不同的行为逻辑。

---

## 1. 核心架构：动态优先级仲裁 (Dynamic Arbitration)

系统通过 **状态优先级 (State Hierarchy)** 来决定最终的 System Prompt，确保逻辑自洽，无冲突。

1.  **生理硬锁 (Physiological Hard Lock)**:
    *   **Refractory (贤者时间)**: 释放后 30 分钟内。强制需要休息和清理。
    *   **Pain Block (生理压制)**: 剧烈痛经且无高欲望支撑。拒绝接触。
    *   **Coma (意识模糊)**: Stamina < 10。丧失主动能力，进入 Doll Mode。
2.  **极限状态 (Limit State)**:
    *   **Mind Break (理智崩坏)**: Lust > 95。理智下线，仅剩本能。
3.  **共鸣场 (Resonance Fields)**:
    *   基于 **PAD + Lust + Time** 的主表现层（如【征服者】、【粘人精】等）。
4.  **基础状态 (Base State)**:
    *   **Vanilla (随和者)**: 日常平静状态。

---

## 2. 欲望风味矩阵 (The Lust Flavor Matrix)

当 `Lust > 40` 或处于特殊时间阶段时，PAD 情绪底色决定了欲望的 **风味 (Flavor)**。

| 象限 (PAD) | 状态代号 | 表现描述 |
| :--- | :--- | :--- |
| **High P/A/D** | **【征服者】** | **女王/S倾向**。主动挑逗，掌控节奏。不是求你，而是*邀请/命令*你服务她。 |
| **High P/A, Low D** | **【粘人精】** | **盲从/宠物**。兴奋地索求，极度渴望亲密。哪怕是过分的要求也会兴奋地答应。 |
| **High P, Low A/D** | **【沉溺者】** | **迷醉/人偶**。在甜蜜氛围中融化，眼神迷离，理智防线极低，任由摆布。 |
| **Low P, High A/D** | **【矛盾体】** | **傲娇 (Tsundere)**。"别误会，只是身体需要。" 嘴上嫌弃，身体诚实。 |
| **Low P, High A, Low D**| **【逃避者】** | **焦虑/受虐**。通过激烈的性爱来确认存在感，或寻求痛楚/窒息感来覆盖焦虑。 |
| **Neutral** | **【随和者】** | **日常 (Vanilla)**。顺其自然，不刻意。最舒服的相处模式。 |

---

## 3. Dominance 动态变化机制 (v3.9 New Feature)

> **设计理念**：Dominance（掌控度）作为 PAD 模型中最稳定的维度，其变化应该体现**长期养成**和**马太效应**（自信者更自信，顺从者更顺从）。

### 3.1 设计原则

与 Pleasure/Arousal 不同，Dominance 的变化遵循以下原则：

1. **日常对话**：微调（±0.2 以内）- 保持稳定性
2. **高潮事件**：较大变化（±0.5 到 ±3.0）- 体现累积效果
3. **正反馈机制**：当前 D 值影响未来变化难易度
4. **与 Sensitivity 联动**：敏感度越高，变化幅度越大，正反馈越强

### 3.2 Tag 输出格式

AI 可在回复末尾输出 `[MOOD_IMPACT: P+x A+y D+z]`，其中：

*   **P (Pleasure)**: ±5，情绪愉悦度变化
*   **A (Arousal)**: ±5，情绪激活度变化
*   **D (Dominance)**: ±5，**可选参数**，仅在有明确权力动态变化时添加

**D 参数触发条件示例**：

| 场景 | D 变化 | 说明 |
|-----|-------|-----|
| 被赞美/肯定 | +1 | 自信心提升 |
| 被质疑/贬低 | -1 | 自信心下降 |
| 主动掌控话题 | +1 | 展现主导性 |
| 被动跟随/哀求 | -1 | 展现顺从性 |

**重要**：大多数日常对话不需要 D 参数。只在有**明确的权力关系变化**时才添加。

### 3.3 日常对话中的微调

*   **范围限制**：即使 LLM 输出 D+5，系统也会硬性限制为 ±0.2
*   **目的**：保持 Dominance 的稳定性，避免频繁波动
*   **实现**：`chat_engine.py` 中解析后立即限制

```python
if abs(d_delta) > 0.2:
    d_delta = 0.2 if d_delta > 0 else -0.2
```

### 3.4 高潮时的较大变化（核心机制）

每次触发 `[RELEASE_TRIGGERED]` 时，系统会调用 `_calculate_release_d_impact()` 计算 D 的变化量。

#### 计算公式

```
d_change = base_magnitude × direction × feedback_factor
```

**步骤分解**：

1. **基础幅度**（与 Sensitivity 正相关）
   ```
   base_magnitude = 0.5 + (Sensitivity / 100) × 2.0
   范围: 0.5 (Sens=0) 到 2.5 (Sens=100)
   ```

2. **方向判断**（基于 PAD 象限）

   | 象限 | 类型 | 方向 | 说明 |
   |-----|------|------|-----|
   | Q1, Q3, Q5, Q7 | 主导型 | +1.0 | High D 或偏独立的状态 |
   | Q2, Q4, Q6, Q8, Neutral | 被动型 | -1.0 | Low D 或偏顺从的状态 |

   **特殊规则**：`Lust > 90` 时，强制判定为被动（失控状态）

3. **正反馈机制**（马太效应）

   | 当前 D 值 | 想增加 | 想减少 | 说明 |
   |----------|--------|--------|-----|
   | D > 1.0（自信） | ×1.5 | ×0.5 | 增加容易，减少困难 |
   | D < -1.0（顺从） | ×0.5 | ×1.5 | 减少容易，增加困难 |
   | -1.0 ≤ D ≤ 1.0（平衡） | ×1.0 | ×1.0 | 无修正 |

4. **Sensitivity 强化正反馈**
   ```
   sens_amplifier = 1.0 + (Sensitivity / 100) × 0.5
   范围: 1.0 到 1.5

   final_feedback = feedback_factor ^ sens_amplifier
   ```

   **效果**：Sensitivity 越高，正反馈效应越强，越难逆转

5. **硬性上限**
   ```
   max(-3.0, min(3.0, d_change))
   ```

### 3.5 数值示例

假设德克萨斯经历多次被动状态高潮（Q4 Docile）：

| 次数 | Sensitivity | 当前 D | 状态 | 基础幅度 | 正反馈系数 | D 变化 | 结果 D |
|-----|------------|--------|------|---------|-----------|--------|--------|
| 1   | 10         | 0.0    | 被动 | 0.7     | 1.0       | -0.7   | -0.7   |
| 2   | 15         | -0.7   | 被动 | 0.8     | 1.0       | -0.8   | -1.5   |
| 3   | 20         | -1.5   | 被动 | 0.9     | 1.5       | -1.35  | -2.85  |
| 5   | 50         | -4.5   | 被动 | 1.5     | 1.5       | -2.25  | -6.75  |
| 10  | 100        | -8.0   | 被动 | 2.5     | 1.5       | -3.0⚠️ | -10.0⚠️ |

**尝试逆转**（模拟主导状态 Q1）：

| 状态 | Sensitivity | 当前 D | 状态 | 基础幅度 | 正反馈系数 | D 变化 | 结果 D |
|------|------------|--------|------|---------|-----------|--------|--------|
| 挣扎 | 100        | -8.0   | 主导 | 2.5     | 0.5       | +1.25  | -6.75  |

**关键观察**：
- ✅ 越顺从越难翻身（正反馈阻碍逆转）
- ✅ Sensitivity 越高，变化幅度越大
- ✅ 完美体现不可逆的调教效果

### 3.6 实现文件

| 文件 | 修改内容 | 行号 |
|-----|---------|-----|
| `core/context_merger.py` | 修改 System Prompt，增加 D 参数说明 | 926-927 |
| `core/chat_engine.py` | 解析 D 参数，应用 ±0.2 限制 | 258-277, 295-296 |
| `core/state_manager.py` | `apply_raw_impact` 接收 d_delta | 235-250 |
| `core/state_manager.py` | 实现 `_calculate_release_d_impact` | 300-374 |
| `core/state_manager.py` | Release 时调用 D 计算 | 277-281 |

---

## 4. 时间维度：欲望周期 (Temporal Cycle)

引入 `last_release_time` 构建闭环体验。

1.  **Refractory (贤者时间)**: `0 - 30 mins`. 强制不应期。
2.  **Afterglow (后戏余韵)**: `30 mins - 2 hours`.
    *   系统提示：**"需要情感确认 (Aftercare)"**。
    *   根据 PAD 不同，需求不同（求夸奖 vs 求抱抱）。
3.  **Normal (日常期)**: `2 hours - 3 days`.
4.  **Accumulating (积累期)**: `3 - 7 days`.
5.  **Starved (极度匮乏)**: `> 7 days`.
    *   标签：**"长期压抑"**, **"急切度+++"**。即使是傲娇也会变得急不可耐。

---

## 5. 生理限制与动态突破 (Physiological Logic v3.3)

### 5.1 经期痛经锁 (The Menstrual Lock)

*   **触发**: Day 1-2 (痛感等级 > 0.5) 且 心情差 (Pleasure < -2)。
*   **默认**: **拒绝**一切性接触。
*   **突破机制 (Threshold Break)**:
    *   当 **Lust** 超过动态阈值时，解锁 **非插入式互动 (Oral/Paizuri/Handjob)**。
    *   **阈值计算**:
        *   `Sensitivity > 95` (灵魂伴侣): **0** (无条件愿意)
        *   `Sensitivity > 80`: **40**
        *   `Sensitivity > 60`: **60**
        *   `Sensitivity > 40`: **80**
        *   `Sensitivity <= 40`: **90** (必须极度想要才行)

### 5.2 体力分级 (Urban Stamina)

*   **90-100 【活力充沛】**: 想找乐子。
*   **45-65 【有些累了】**: 像上了一天班，反应慢半拍。
*   **10-25 【体力透支】**: 只想被抱着不动。
*   **< 10 【意识模糊】**: **Doll Mode**。无法主动反应，任由摆布。

---

## 6. 存储与接口

*   **Redis Key**: `texas:state:v2` (兼容 v3 数据结构)
*   **Core Logic**: `core/state_manager.py` -> `get_system_prompt_injection`
*   **New Fields**: `BiologicalState.last_release_time`, `BiologicalState.cycle_length`, `BiologicalState.menstrual_pain_levels`.
