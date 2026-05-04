set MQSERVER=DEV.APP.SVRCONN/TCP/127.0.0.1(1415)

echo %MQSERVER%
pause
amqsruac -m QM1 -c CPU -t QMgrSummary -n 1
amqsruac -m QM1 -c DISK -n 1 


