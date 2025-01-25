/* 
 * File:   pdct_main.cpp
 * Author: luciamarock
 *
 * Created on 5 novembre 2016, 14.00
 */

#include <cstdlib>
#include <cstdio>
#include <cstdarg>
#include "cPdctOptions.h"
#include "cPdctMain.h"

/*
 * 
 */
int main(int argc, char** argv)
{
    fprintf(stdout, "Start Of Program\n");
    
    /* get command line options, and run program */
    cPdctOptions aMainOptions;
    if (aMainOptions.parseCommandLine(argc, argv)) {
        cPdctMain aMainProgram;
        aMainProgram.run(aMainOptions);
    } else {
        fprintf(stderr, "Error: Failed to parse command line options\n");
        return 1;
    }
    
    fprintf(stdout, "End Of Program\n");
    return 0;
}