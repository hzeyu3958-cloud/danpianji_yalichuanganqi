#include <stdint.h>
#include <stdio.h>

#include <ti/devices/cc26x0r2/driverlib/ioc.h>
#include <ti/drivers/ADC.h>
#include <ti/drivers/GPIO.h>
#include <ti/drivers/UART.h>
#include <ti/drivers/dpl/ClockP.h>

#include "Board.h"

#define SAMPLE_PERIOD_US 20000U

volatile uint32_t firmwareStage = 0;
volatile uint32_t firmwareSamples = 0;

void *mainThread(void *arg0)
{
    ADC_Handle adc;
    ADC_Params adcParams;
    UART_Handle uart;
    UART_Params uartParams;
    uint16_t raw;
    uint32_t millivolts;
    uint32_t elapsedMs = 0;
    char line[64];

    firmwareStage = 1;
    GPIO_init();
    UART_init();

    GPIO_setConfig(Board_GPIO_LED0, GPIO_CFG_OUT_STD | GPIO_CFG_OUT_LOW);

    UART_Params_init(&uartParams);
    uartParams.writeDataMode = UART_DATA_BINARY;
    uartParams.readDataMode = UART_DATA_BINARY;
    uartParams.readEcho = UART_ECHO_OFF;
    uartParams.baudRate = 115200;
    uart = UART_open(Board_UART0, &uartParams);

    if (uart == NULL) {
        firmwareStage = 0xE1;
        while (1) {}
    }
    firmwareStage = 2;
    UART_write(uart, "READY\r\n", 7);

    firmwareStage = 3;
    ADC_init();
    ADC_Params_init(&adcParams);
    adc = ADC_open(Board_ADC0, &adcParams);

    if (adc == NULL) {
        firmwareStage = 0xE2;
        while (1) {
            UART_write(uart, "ERR,ADC\r\n", 9);
            ClockP_usleep(500000U);
        }
    }

    /* Sensor wiring: 3V3 -- resistive pressure sensor -- DIO23. */
    IOCIOPortPullSet(IOID_23, IOC_IOPULL_DOWN);
    firmwareStage = 4;
    GPIO_write(Board_GPIO_LED0, Board_GPIO_LED_ON);

    while (1) {
        if (ADC_convert(adc, &raw) == ADC_STATUS_SUCCESS) {
            firmwareSamples++;
            millivolts = ADC_convertRawToMicroVolts(adc, raw) / 1000U;
            int length = snprintf(line, sizeof(line), "P,%lu,%u,%lu\r\n",
                                  (unsigned long)elapsedMs,
                                  (unsigned int)raw,
                                  (unsigned long)millivolts);
            UART_write(uart, line, (size_t)length);
        }
        elapsedMs += 20U;
        ClockP_usleep(SAMPLE_PERIOD_US);
    }
}
