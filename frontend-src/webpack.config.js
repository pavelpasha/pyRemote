const path = require('path');
const miniCss = require('mini-css-extract-plugin');

module.exports = {
    entry: {
        main: './src/js/index.js',
        log: './src/js/log.js',
    },
    output: {
        path: path.resolve(__dirname, '../static'),
        filename: 'js/[name].js'
    },
    module: {
        rules: [{
            test: /\.(s*)css$/,
            use: [
                miniCss.loader,
                'css-loader',
                'sass-loader',
            ]
        }, {
            test: /\.(png|jpe?g|gif)$/i,
            loader: 'file-loader',
            options: {
                name: '../img/[name].[ext]',
            }
        }]
    },
    plugins: [
        new miniCss({
            filename: 'css/[name].css',
        }),
    ]
};