# CC2640R2 柔性压力传感器监测

## 接线

当前固件支持两种接法。用户要求的“仅两根杜邦线”接法为：

```text
LaunchPad 3V3 ---- 压力传感器 ---- DIO23
```

固件在 DIO23 启用内部下拉。注意这里必须是**下拉**，不能是上拉；传感器另一端已经接 3V3，再上拉会使 ADC 接近恒定高电平。内部电阻误差较大，只适合显示压力相对变化。

需要准确、稳定测量时，推荐按下列方式接外部电阻：

```text
LaunchPad 3V3 ---- 压力传感器 ----+---- DIO23 / ADC 输入
                                  |
                                10 kΩ
                                  |
LaunchPad GND --------------------+---- GND
```

- 传感器无极性。
- 必须使用 `3V3`，不要接 `5V`，CC2640R2 输入不耐 5 V。
- 10 kΩ 是起始推荐值；若曲线变化太小，可在 4.7 kΩ～47 kΩ 间调整，并同步修改上位机“分压电阻”。
- DIO23 对应 CC2640R2 的模拟输入通道。不要用照片中间那排 XDS110 调试跳线作为传感器接口。

## 上位机

双击 `run.bat`，程序会优先选择 `XDS110 Class Application/User UART`（本机当前为 COM17），波特率固定 115200。

1. 未烧录前可以点“模拟数据”检查实时曲线。
2. 烧录后选择 COM17，点“连接”。
3. 传感器无载时点“去皮 / 当前置零”。
4. 传感器说明书给出的标定关系为 `F = p1 * G + p2`。将实际标定得到的 p1、p2 填入界面。
5. “开始保存 CSV”可保存电脑时间、ADC、电压、电导和力值。

上位机还提供实验性脉搏检测：对 ADC 做 0.7–4 Hz Butterworth 带通滤波，使用自适应阈值和 300 ms 不应期检测波峰。启动后先稳定 5 秒；突然的大幅 ADC 变化会判为运动干扰，暂停心率更新 2 秒并重新确认。只有至少 3 个周期一致、处于 40–200 BPM 范围内时才显示心率，图中的紫色圆点表示有效波峰。CSV 同时保存带通信号、有效波峰、BPM 和信号质量。

实时图纵坐标默认固定为 ±20，不会随数据自动变化；在图上滚动鼠标滚轮才会缩放纵坐标。侧栏“周边压力补偿 (N)”默认是 0.020，可按实际测得的周边下压值修改，填 0 可关闭。该补偿只作用于力值显示和 CSV 的力值列，脉搏带通信号不受直流补偿影响。

单个压力传感器无法从电信号判断压力来自正面还是背面。滤波只能抑制慢压和突然移动，安装时仍需在传感器背面放硬质 PET/亚克力支撑板、仅固定边缘，并避免桌面或胶带直接挤压敏感区；需要真正区分两侧压力时，应增加第二片参考传感器做差分。

串口协议为 ASCII 行：`P,设备毫秒,ADC原始值,电压mV`，例如 `P,1240,1875,1511`。

## 已验证固件工程

实际烧录使用 `firmware/nortos_gcc`，基于 SimpleLink CC2640R2 SDK 4.30 的官方 NoRTOS UART 示例。固件已在 LAUNCHXL-CC2640R2 上验证，COM17 以 115200 波特率、约 50 Hz 输出 ADC 数据。

SDK 的预编译库必须配套 `GNU Arm Embedded 7-2017-q4-major`。使用 GCC 12 虽然可能链接成功，但程序不能正常启动串口。

在 `firmware/nortos_gcc/gcc` 目录构建：

```powershell
gmake clean SIMPLELINK_CC2640R2_SDK_INSTALL_DIR="D:/path/simplelink_cc2640r2_sdk_4_30_00_08" GCC_ARMCOMPILER="D:/path/gcc-arm-none-eabi-7-2017-q4-major"
gmake SIMPLELINK_CC2640R2_SDK_INSTALL_DIR="D:/path/simplelink_cc2640r2_sdk_4_30_00_08" GCC_ARMCOMPILER="D:/path/gcc-arm-none-eabi-7-2017-q4-major"
```

输出文件为 `pressure_sensor.out`。

## CCS TI-RTOS 参考工程

固件依赖支持 CC2640R2 LaunchPad 的 SimpleLink CC2640R2 SDK。CCS 只是 IDE；只有 CCS 而没有该 SDK 无法编译。

1. 在 CCS Resource Explorer 中导入：`SimpleLink CC2640R2 SDK -> Examples -> LAUNCHXL-CC2640R2 -> TI Drivers -> empty -> tirtos -> CCS Compiler`。
2. 将示例的 `empty.c` 排除编译，把本目录的 `main_tirtos.c`、`pressure_sensor.c`、`pressure_sensor.h` 加入工程。
3. 在工程的 `Board.h` / `CC2640R2_LAUNCHXL.h` 中确认 `Board_ADC0` 映射到 `CC2640R2_LAUNCHXL_ADC0`，默认就是 DIO23；`Board_UART0` 使用 XDS110 回传串口。
4. Build 后用板载 XDS110 Debug/Flash。运行后 COM17 应每秒收到约 50 行数据。

不同版本 SDK 的 `empty` 示例配置文件名称会略有差别，所以这里复用 SDK 自带、已经验证过的板级配置和链接脚本，不复制易过期的工程元数据。

## 标定

压力片个体差异较大，照片和说明书没有给出 p1、p2，不能凭空得到准确牛顿值。至少用两个已知载荷测量：记录无载/已知载荷时上位机显示的电导 G，然后线性计算：

```text
p1 = (F2 - F1) / (G2 - G1)
p2 = F1 - p1 * G1
```

未标定时仍可稳定显示压力的相对变化，但界面的 N 数值仅是相对量。
